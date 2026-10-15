#!/usr/bin/env python3
"""Gera o card "Telemetria da Grade" (SVG) a partir do calendário de contribuições.

Usa o mesmo calendário do perfil público. Com "Include private contributions on
my profile" ativado, as contribuições privadas entram na contagem (só a
quantidade, sem nome de repositório).

Uso:
    GITHUB_TOKEN=... python telemetria.py <login> <saida.svg>
    python telemetria.py --mock <saida.svg>      # dados falsos, para testar o visual
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.github.com/graphql"


# --------------------------------------------------------------------------- dados

def gql(query: str, variables: dict, token: str) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "telemetria-da-grade",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", payload["errors"]))
    return payload["data"]


Q_RESUMO = """
query($login: String!) {
  user(login: $login) {
    createdAt
    contributionsCollection {
      contributionYears
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}"""

Q_ANO = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


def dias_do_calendario(cal: dict) -> dict[date, int]:
    return {
        date.fromisoformat(d["date"]): d["contributionCount"]
        for w in cal["weeks"]
        for d in w["contributionDays"]
    }


def coletar(login: str, token: str) -> dict:
    u = gql(Q_RESUMO, {"login": login}, token)["user"]
    if u is None:
        raise RuntimeError(f"usuário {login!r} não encontrado")
    cc = u["contributionsCollection"]
    ultimo_ano = dias_do_calendario(cc["contributionCalendar"])

    # histórico completo, ano a ano, para total geral e maior sequência
    historico: dict[date, int] = {}
    for ano in sorted(cc["contributionYears"]):
        d = gql(
            Q_ANO,
            {"login": login, "from": f"{ano}-01-01T00:00:00Z", "to": f"{ano}-12-31T23:59:59Z"},
            token,
        )
        historico.update(dias_do_calendario(d["user"]["contributionsCollection"]["contributionCalendar"]))
    historico.update(ultimo_ano)  # o calendário corrente é a fonte mais fresca

    return {
        "criado_em": u["createdAt"][:4],
        "total_12m": cc["contributionCalendar"]["totalContributions"],
        "privadas_12m": cc["restrictedContributionsCount"],
        "commits_12m": cc["totalCommitContributions"],
        "prs_12m": cc["totalPullRequestContributions"],
        "issues_12m": cc["totalIssueContributions"],
        "reviews_12m": cc["totalPullRequestReviewContributions"],
        "ultimo_ano": ultimo_ano,
        "historico": historico,
    }


def mock() -> dict:
    random.seed(64)
    hoje = date.today()
    hist = {}
    for i in range(3 * 365):
        d = hoje - timedelta(days=i)
        p = 0.35 if i > 200 else 0.75
        hist[d] = random.choice([1, 2, 3, 5, 8, 13]) if random.random() < p else 0
    ultimo = {d: c for d, c in hist.items() if (hoje - d).days < 365}
    tot = sum(ultimo.values())
    return {
        "criado_em": str(hoje.year - 3), "total_12m": tot, "privadas_12m": int(tot * 0.7),
        "commits_12m": int(tot * 0.25), "prs_12m": 4, "issues_12m": 2, "reviews_12m": 1,
        "ultimo_ano": ultimo, "historico": hist,
    }


# --------------------------------------------------------------------------- métricas

def sequencias(dias: dict[date, int], hoje: date) -> tuple[int, int, date | None, date | None]:
    """(atual, maior, início_maior, fim_maior). Hoje zerado não quebra a sequência atual."""
    atual = 0
    d = hoje if dias.get(hoje, 0) > 0 else hoje - timedelta(days=1)
    while dias.get(d, 0) > 0:
        atual += 1
        d -= timedelta(days=1)

    maior, ini_m, fim_m = 0, None, None
    corrida, ini, prev = 0, None, None
    for d in sorted(dias):
        if dias[d] > 0:
            if corrida == 0 or prev is None or (d - prev).days != 1:
                corrida, ini = 1, d
            else:
                corrida += 1
            if corrida > maior:
                maior, ini_m, fim_m = corrida, ini, d
        else:
            corrida = 0
        prev = d
    return atual, maior, ini_m, fim_m


def semanas(dias: dict[date, int], hoje: date, n: int = 52) -> list[int]:
    out = []
    for k in range(n - 1, -1, -1):
        fim = hoje - timedelta(days=7 * k)
        out.append(sum(dias.get(fim - timedelta(days=i), 0) for i in range(7)))
    return out


def br(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def dm(d: date | None) -> str:
    return d.strftime("%d/%m/%y") if d else "--"


# --------------------------------------------------------------------------- SVG

def render(dados: dict) -> str:
    hoje = datetime.now(timezone(timedelta(hours=-3))).date()
    atual, maior, ini_m, fim_m = sequencias(dados["historico"], hoje)
    total_geral = sum(dados["historico"].values())
    pico_dia, pico_n = max(dados["ultimo_ano"].items(), key=lambda kv: kv[1], default=(None, 0))
    sem = semanas(dados["ultimo_ano"], hoje)

    W, H = 1200, 330
    mono = "'Fira Code','JetBrains Mono',Consolas,Menlo,'DejaVu Sans Mono',monospace"

    tiles = [
        ("CONTRIBUIÇÕES · 12 MESES", br(dados["total_12m"]), f"{br(dados['privadas_12m'])} em repositórios privados", "#00f0ff"),
        ("SEQUÊNCIA ATUAL", f"{atual}", "dia" if atual == 1 else "dias seguidos", "#ff7a1a"),
        ("MAIOR SEQUÊNCIA", f"{maior}", f"{dm(ini_m)} → {dm(fim_m)}" if maior else "aguardando o primeiro rastro", "#00f0ff"),
        (f"TOTAL DESDE {dados['criado_em']}", br(total_geral), "contribuições na Grade", "#00f0ff"),
    ]
    tw, tg, tx0, ty = 270, 20, 30, 70
    tiles_svg = []
    for i, (rot, val, sub, cor) in enumerate(tiles):
        x = tx0 + i * (tw + tg)
        cls = "num pulse" if i == 1 and atual > 0 else "num"
        tiles_svg.append(f'''
    <g transform="translate({x},{ty})">
      <rect width="{tw}" height="118" rx="2" fill="#071019" stroke="#0e3a44"/>
      <path d="M0 14 V0 H14 M{tw-14} 0 H{tw} V14" stroke="{cor}" stroke-width="2" fill="none"/>
      <text x="16" y="28" class="lbl">{rot}</text>
      <text x="16" y="80" class="{cls}" fill="{cor}" filter="url(#glow)">{val}</text>
      <text x="16" y="103" class="sub">{sub}</text>
    </g>''')

    # trilha semanal
    gx, gy, gw, gh = 30, 222, 1140, 70
    mx = max(sem) or 1
    pts = [(gx + i * gw / (len(sem) - 1), gy + gh - (v / mx) * gh) for i, v in enumerate(sem)]
    linha = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"M{gx},{gy+gh} L" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" L{gx+gw},{gy+gh} Z"
    imax = sem.index(max(sem))
    px, py = pts[imax]

    detalhe = (
        f"commits públicos {br(dados['commits_12m'])}  ·  PRs {br(dados['prs_12m'])}  ·  "
        f"issues {br(dados['issues_12m'])}  ·  reviews {br(dados['reviews_12m'])}  ·  "
        f"pico {br(pico_n)} em {dm(pico_dia)}"
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="tt dd">
  <title id="tt">Telemetria da Grade</title>
  <desc id="dd">{br(dados["total_12m"])} contribuições nos últimos 12 meses, sequência atual de {atual} dias, maior sequência de {maior} dias, {br(total_geral)} contribuições desde {dados["criado_em"]}.</desc>
  <defs>
    <filter id="glow" x="-20%" y="-50%" width="140%" height="200%">
      <feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#00f0ff" stop-opacity="0.35"/>
      <stop offset="1" stop-color="#00f0ff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <style>
    .lbl {{ font: 600 12px {mono}; letter-spacing: 2px; fill: #5fd9e6; }}
    .num {{ font: 700 46px {mono}; }}
    .sub {{ font: 13px {mono}; fill: #8fb9c2; }}
    .hud {{ font: 12px {mono}; letter-spacing: 2px; fill: #5fd9e6; }}
    .det {{ font: 12px {mono}; fill: #8fb9c2; }}
    .trail {{ stroke-dasharray: 1000; stroke-dashoffset: 1000; animation: draw 2.4s ease-out .3s forwards; }}
    @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
    .pulse {{ animation: pulse 2.4s ease-in-out infinite; }}
    @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: .55; }} }}
    @media (prefers-reduced-motion: reduce) {{ .trail {{ animation: none; stroke-dashoffset: 0; }} .pulse {{ animation: none; }} }}
  </style>

  <rect width="{W}" height="{H}" fill="#05070d"/>
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" fill="none" stroke="#0e3a44"/>
  <g stroke="#00f0ff" stroke-width="2" fill="none">
    <path d="M10 30 V10 H30"/><path d="M{W-30} 10 H{W-10} V30"/>
    <path d="M10 {H-30} V{H-10} H30"/><path d="M{W-30} {H-10} H{W-10} V{H-30}"/>
  </g>

  <text x="30" y="44" class="hud" style="fill:#bff8ff;font-size:14px;letter-spacing:4px">TELEMETRIA DA GRADE</text>
  <text x="{W-30}" y="44" class="hud" text-anchor="end">SINAL ATUALIZADO {hoje.strftime("%d/%m/%Y")}</text>
  {"".join(tiles_svg)}

  <text x="30" y="212" class="hud">RASTRO SEMANAL · 52 SEMANAS</text>
  <text x="{W-30}" y="212" class="det" text-anchor="end">{detalhe}</text>
  <line x1="{gx}" y1="{gy+gh}" x2="{gx+gw}" y2="{gy+gh}" stroke="#0e3a44"/>
  <path d="{area}" fill="url(#area)"/>
  <polyline class="trail" pathLength="1000" points="{linha}" fill="none" stroke="#00f0ff" stroke-width="2" stroke-linejoin="round" filter="url(#glow)"/>
  <circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#ff7a1a" filter="url(#glow)"/>
</svg>
'''


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--mock":
        dados, saida = mock(), sys.argv[2]
    elif len(sys.argv) == 3:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN ausente")
        dados, saida = coletar(sys.argv[1], token), sys.argv[2]
    else:
        sys.exit(__doc__)
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write(render(dados))
    print(f"ok: {saida} | 12m={dados['total_12m']} privadas={dados['privadas_12m']}")


if __name__ == "__main__":
    main()
