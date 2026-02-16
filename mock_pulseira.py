import pygame
import requests
import sys
import threading
import time
import math
import io
from datetime import datetime

SERVIDOR_URL = "http://127.0.0.1:5000"

ESCALA = 3
REAL_W = 128
REAL_H = 160
LARGURA = REAL_W * ESCALA
ALTURA = REAL_H * ESCALA
FPS = 30
INTERVALO_CHECK = 30
TEMPO_REALARME = 300

PRETO = (10, 10, 18)
FUNDO = (16, 20, 30)
FUNDO_CARD = (24, 30, 46)
FUNDO_CARD_LIGHT = (32, 40, 58)
AZUL = (66, 135, 245)
AZUL_CLARO = (100, 165, 255)
AZUL_ESCURO = (30, 60, 120)
VERDE = (46, 204, 113)
VERDE_CLARO = (60, 220, 130)
VERMELHO = (235, 77, 75)
VERMELHO_CLARO = (255, 100, 100)
AMARELO = (255, 209, 50)
AMARELO_CLARO = (255, 225, 100)
BRANCO = (235, 240, 250)
CINZA = (120, 130, 150)
CINZA_CLARO = (160, 170, 185)
CINZA_ESCURO = (60, 68, 85)
ACCENT = (138, 100, 255)


class Estado:
    def __init__(self):
        self.agenda = []
        self.config = {"horario_sono_inicio": "23:00", "horario_sono_fim": "07:00"}
        self.paciente = ""
        self.conectada = False
        self.tela = "inicio"
        self.alarme_ativo = False
        self.alarme_med = None
        self.alarme_img = None
        self.alarme_viu = False
        self.alarme_tomou = False
        self.alarme_inicio = None
        self.vibrando = False
        self.ciclo = 0
        self.alertados = set()
        self.sync = None
        self.frame = 0
        self.tela_foto_fullscreen = False
        self.foto_fullscreen_surface = None


e = Estado()


def hmin(h):
    p = h.split(":")
    return int(p[0]) * 60 + int(p[1])


def nsono(h, c):
    si = hmin(c.get("horario_sono_inicio", "23:00"))
    sf = hmin(c.get("horario_sono_fim", "07:00"))
    v = hmin(h)
    return (v >= si or v < sf) if si > sf else (si <= v < sf)


def buscar():
    try:
        r = requests.get(f"{SERVIDOR_URL}/api/agenda", timeout=5)
        if r.status_code == 200:
            d = r.json()
            e.agenda = d.get("medicamentos", [])
            e.config = d.get("configuracoes", e.config)
            e.paciente = d.get("paciente", {}).get("nome", "")
            e.conectada = True
            e.sync = datetime.now()
            return True
    except:
        e.conectada = False
    return False


def carregar_img_raw(nome):
    try:
        url = f"{SERVIDOR_URL}/api/imagens/{nome}"
        print(f"Baixando imagem: {url}")
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            img_bytes = io.BytesIO(r.content)
            img = pygame.image.load(img_bytes)
            return img
    except Exception as err:
        print(f"Erro imagem: {err}")
    return None


def carregar_img_fullscreen(nome):
    img = carregar_img_raw(nome)
    if img is None:
        return None
    w, h = img.get_size()
    ratio = max(LARGURA / w, ALTURA / h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    scaled = pygame.transform.scale(img, (new_w, new_h))
    final = pygame.Surface((LARGURA, ALTURA))
    final.fill(PRETO)
    x = (LARGURA - new_w) // 2
    y = (ALTURA - new_h) // 2
    final.blit(scaled, (x, y))
    return final


def confirmar(med):
    try:
        requests.post(f"{SERVIDOR_URL}/api/confirmar", json={
            "medicamento": med["nome"],
            "horario": med.get("horario_disparado", med["horario"][0]),
            "horario_real": datetime.now().strftime("%H:%M:%S"),
            "data": datetime.now().strftime("%d/%m/%Y"),
        }, timeout=5)
        buscar()
    except:
        pass


def alarmar(med, horario_disparado):
    e.alarme_ativo = True
    e.alarme_med = med
    e.alarme_med["horario_disparado"] = horario_disparado
    e.alarme_viu = False
    e.alarme_tomou = False
    e.alarme_inicio = datetime.now()
    e.vibrando = True
    e.ciclo = 0
    e.tela = "alarme"
    e.tela_foto_fullscreen = False
    e.foto_fullscreen_surface = None
    e.alarme_img = None
    if med.get("img_arquivo"):
        e.foto_fullscreen_surface = carregar_img_fullscreen(med["img_arquivo"])
        if e.foto_fullscreen_surface:
            e.alarme_img = True


def t_horarios():
    while True:
        time.sleep(INTERVALO_CHECK)
        if not e.conectada or e.alarme_ativo:
            continue
        buscar()
        agora = datetime.now()
        ha = agora.strftime("%H:%M")
        for med in e.agenda:
            horarios = med.get("horario", [])
            if not isinstance(horarios, list):
                horarios = [horarios]
            for hmed in horarios:
                ch = f"{med['nome']}_{hmed}_{agora.strftime('%Y%m%d_%H%M')}"
                if ha == hmed and ch not in e.alertados:
                    cat = med.get("categoria", "normal")
                    if nsono(ha, e.config) and cat == "normal":
                        e.alertados.add(ch)
                        continue
                    e.alertados.add(ch)
                    alarmar(med, hmed)
                    break


def t_realarme():
    while True:
        time.sleep(10)
        if not e.alarme_ativo or e.alarme_tomou:
            continue
        if e.alarme_viu and not e.alarme_tomou:
            if (datetime.now() - e.alarme_inicio).total_seconds() >= TEMPO_REALARME:
                e.vibrando = True
                e.alarme_viu = False
                e.alarme_inicio = datetime.now()
                e.ciclo = 0
                e.tela_foto_fullscreen = False


def prox():
    if not e.agenda:
        return None
    ha = datetime.now().strftime("%H:%M")
    lista_futura = []
    for m in e.agenda:
        if not m.get("ativo", True):
            continue
        hs = m.get("horario", [])
        if not isinstance(hs, list):
            hs = [hs]
        for h in hs:
            if h >= ha:
                lista_futura.append((h, m))
    lista_futura.sort(key=lambda x: x[0])
    if lista_futura:
        h, m = lista_futura[0]
        m_copy = dict(m)
        m_copy["horario_prox"] = h
        return m_copy
    return None


def tx(tela, texto, x, y, tam=12, cor=BRANCO, centro=False, bold=False):
    try:
        f = pygame.font.SysFont("arial", tam * ESCALA, bold=bold)
    except:
        f = pygame.font.Font(None, tam * ESCALA)
    s = f.render(texto, True, cor)
    if centro:
        r = s.get_rect(center=(x * ESCALA, y * ESCALA))
        tela.blit(s, r)
    else:
        tela.blit(s, (x * ESCALA, y * ESCALA))
    return s.get_width() // ESCALA


def rect(tela, x, y, w, h, cor, raio=6):
    r = pygame.Rect(x * ESCALA, y * ESCALA, w * ESCALA, h * ESCALA)
    pygame.draw.rect(tela, cor, r, border_radius=raio * ESCALA)
    return r


def btn(tela, texto, x, y, w, h, cor, cor_hover, mp, cor_txt=BRANCO, raio=8, tam_fonte=11):
    r = pygame.Rect(x * ESCALA, y * ESCALA, w * ESCALA, h * ESCALA)
    hover = r.collidepoint(mp)
    c = cor_hover if hover else cor
    sombra = pygame.Rect((x + 1) * ESCALA, (y + 2) * ESCALA, w * ESCALA, h * ESCALA)
    pygame.draw.rect(tela, (0, 0, 0, 40), sombra, border_radius=raio * ESCALA)
    pygame.draw.rect(tela, c, r, border_radius=raio * ESCALA)
    if hover:
        brilho = pygame.Rect(x * ESCALA, y * ESCALA, w * ESCALA, (h // 2) * ESCALA)
        s = pygame.Surface((brilho.width, brilho.height), pygame.SRCALPHA)
        s.fill((255, 255, 255, 15))
        tela.blit(s, brilho)
    tx(tela, texto, x + w // 2, y + h // 2, tam_fonte, cor_txt, centro=True, bold=True)
    return r


def barra_topo(tela):
    rect(tela, 0, 0, REAL_W, 16, PRETO)
    agora = datetime.now()
    tx(tela, agora.strftime("%H:%M"), 5, 2, 9, CINZA, bold=True)
    cor_c = VERDE if e.conectada else VERMELHO
    cx = (REAL_W - 12) * ESCALA
    cy = 8 * ESCALA
    pygame.draw.circle(tela, cor_c, (cx, cy), 4 * ESCALA)
    pygame.draw.circle(tela, cor_c, (cx, cy), 6 * ESCALA, 1 * ESCALA)
    pygame.draw.line(tela, CINZA_ESCURO, (4 * ESCALA, 16 * ESCALA),
                     ((REAL_W - 4) * ESCALA, 16 * ESCALA), 1)


def truncar(texto, max_chars):
    if len(texto) > max_chars:
        return texto[:max_chars - 1] + "..."
    return texto


def tela_inicio(tela, mp):
    tela.fill(FUNDO)
    rect(tela, 20, 30, 88, 60, FUNDO_CARD, 12)
    cx = REAL_W // 2 * ESCALA
    cy = 45 * ESCALA
    pygame.draw.circle(tela, AZUL_ESCURO, (cx, cy), 14 * ESCALA)
    pygame.draw.circle(tela, AZUL, (cx, cy), 10 * ESCALA)
    tx(tela, "+", REAL_W // 2, 45, 16, BRANCO, centro=True, bold=True)
    tx(tela, "PINAID", REAL_W // 2, 68, 16, BRANCO, centro=True, bold=True)
    tx(tela, "Cuidado Inteligente", REAL_W // 2, 80, 7, CINZA, centro=True)
    cor_st = VERDE if e.conectada else CINZA
    txt_st = "Servidor online" if e.conectada else "Desconectado"
    tx(tela, txt_st, REAL_W // 2, 100, 8, cor_st, centro=True)
    b = btn(tela, "INICIAR", 20, 118, 88, 28, AZUL, AZUL_CLARO, mp)
    return {"conectar": b}


def tela_relogio(tela, mp):
    tela.fill(FUNDO)
    barra_topo(tela)
    agora = datetime.now()
    tx(tela, agora.strftime("%H:%M"), REAL_W // 2, 32, 30, BRANCO, centro=True, bold=True)
    tx(tela, agora.strftime(":%S"), REAL_W // 2 + 38, 36, 10, CINZA)
    dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    dia_nome = dias[agora.weekday()]
    tx(tela, f"{dia_nome}, {agora.strftime('%d/%m')}", REAL_W // 2, 50, 8, CINZA_CLARO, centro=True)
    pygame.draw.line(tela, CINZA_ESCURO, (16 * ESCALA, 58 * ESCALA),
                     ((REAL_W - 16) * ESCALA, 58 * ESCALA), 1)
    p = prox()
    if p:
        rect(tela, 8, 63, 112, 62, FUNDO_CARD, 8)
        cat = p.get("categoria", "normal")
        cor_barra = VERMELHO if cat == "essencial" else AZUL
        rect(tela, 8, 63, 3, 62, cor_barra, 2)
        tx(tela, "PROXIMO REMEDIO", REAL_W // 2 + 2, 69, 7, CINZA, centro=True)
        nome = truncar(p["nome"].upper(), 14)
        tx(tela, nome, REAL_W // 2 + 2, 82, 14, BRANCO, centro=True, bold=True)
        h_show = p.get("horario_prox", "--:--")
        rect(tela, 34, 96, 64, 16, AZUL_ESCURO, 4)
        tx(tela, h_show, REAL_W // 2 + 2, 104, 13, AZUL_CLARO, centro=True, bold=True)
        dose = truncar(p.get("dose", ""), 20)
        tx(tela, dose, REAL_W // 2 + 2, 118, 7, CINZA_CLARO, centro=True)
    else:
        rect(tela, 8, 63, 112, 62, FUNDO_CARD, 8)
        tx(tela, "Nenhum", REAL_W // 2, 85, 12, CINZA, centro=True)
        tx(tela, "remedio", REAL_W // 2, 100, 12, CINZA, centro=True)
    if e.paciente:
        tx(tela, truncar(e.paciente, 18), REAL_W // 2, 132, 7, CINZA_ESCURO, centro=True)
    b = btn(tela, "ATUALIZAR", 24, 140, 80, 16, FUNDO_CARD_LIGHT, CINZA_ESCURO, mp, CINZA_CLARO, 6)
    return {"sync": b}


def tela_alarme(tela, mp):
    med = e.alarme_med
    botoes = {}

    if e.vibrando:
        e.ciclo += 1
        intensidade = (math.sin(e.ciclo * 0.12) + 1) / 2
        r = int(25 + intensidade * 30)
        g = int(8 + intensidade * 5)
        b_val = int(8 + intensidade * 5)
        tela.fill((r, g, b_val))
        for i in range(3):
            pygame.draw.rect(tela, (VERMELHO[0], VERMELHO[1], VERMELHO[2]),
                             pygame.Rect((2 + i) * ESCALA, (2 + i) * ESCALA,
                                         (REAL_W - 4 - i * 2) * ESCALA,
                                         (REAL_H - 4 - i * 2) * ESCALA),
                             1, border_radius=4 * ESCALA)
        barra_topo(tela)
        vib_offset = int(math.sin(e.ciclo * 0.3) * 2)
        tx(tela, "VIBRANDO", REAL_W // 2 + vib_offset, 24, 9, VERMELHO_CLARO, centro=True, bold=True)
        tx(tela, "HORA DO REMEDIO", REAL_W // 2, 36, 12, BRANCO, centro=True, bold=True)
        rect(tela, 8, 48, 112, 48, FUNDO_CARD, 8)
        nome = truncar(med["nome"].upper(), 14)
        tx(tela, nome, REAL_W // 2, 58, 15, BRANCO, centro=True, bold=True)
        h_show = med.get("horario_disparado", "--:--")
        rect(tela, 34, 70, 60, 14, AZUL_ESCURO, 4)
        tx(tela, h_show, REAL_W // 2, 77, 12, AZUL_CLARO, centro=True, bold=True)
        dose = truncar(med.get("dose", ""), 22)
        tx(tela, dose, REAL_W // 2, 90, 7, CINZA_CLARO, centro=True)
        botoes["ja_vi"] = btn(tela, "JA VI", 10, 104, 108, 26, AMARELO, AMARELO_CLARO, mp, PRETO)
    else:
        tela.fill(FUNDO)
        barra_topo(tela)
        tx(tela, "CONFIRME A DOSE", REAL_W // 2, 24, 10, AZUL, centro=True, bold=True)

        # Card info
        rect(tela, 8, 34, 112, 44, FUNDO_CARD, 8)
        nome = truncar(med["nome"].upper(), 14)
        tx(tela, nome, REAL_W // 2, 42, 14, BRANCO, centro=True, bold=True)
        h_show = med.get("horario_disparado", "--:--")
        rect(tela, 34, 54, 60, 14, AZUL_ESCURO, 4)
        tx(tela, h_show, REAL_W // 2, 61, 12, AZUL_CLARO, centro=True, bold=True)
        dose = truncar(med.get("dose", ""), 22)
        tx(tela, dose, REAL_W // 2, 72, 7, CINZA_CLARO, centro=True)

        tem_foto = e.alarme_img is not None

        if tem_foto:
            # Botoes UM ACIMA DO OUTRO com largura total
            botoes["ver_foto"] = btn(tela, "VER FOTO", 10, 86, 108, 22,
                                     ACCENT, (160, 120, 255), mp, BRANCO, 6, 11)
            botoes["tomei"] = btn(tela, "JA TOMEI", 10, 114, 108, 22,
                                  VERDE, VERDE_CLARO, mp, BRANCO, 6, 11)
        else:
            # Sem foto: botao TOMEI grande
            botoes["tomei"] = btn(tela, "JA TOMEI", 10, 100, 108, 26,
                                  VERDE, VERDE_CLARO, mp, BRANCO, 8, 12)

        # Re-alarme countdown
        if e.alarme_inicio:
            t = max(0, TEMPO_REALARME - (datetime.now() - e.alarme_inicio).total_seconds())
            m_val = int(t // 60)
            s_val = int(t % 60)
            tx(tela, f"Re-alarme: {m_val}:{s_val:02d}", REAL_W // 2, 145, 7,
               VERMELHO if t < 60 else CINZA_ESCURO, centro=True, bold=t < 60)

    return botoes


def tela_foto_full(tela):
    """Foto 100% da tela, sem textos, sem overlays."""
    if e.foto_fullscreen_surface:
        tela.blit(e.foto_fullscreen_surface, (0, 0))
    else:
        tela.fill(PRETO)
    return {}


def tela_ok(tela, mp):
    tela.fill(FUNDO)
    barra_topo(tela)
    med = e.alarme_med
    cx = REAL_W // 2 * ESCALA
    cy = 52 * ESCALA
    pygame.draw.circle(tela, VERDE, (cx, cy), 22 * ESCALA, 2 * ESCALA)
    s = pygame.Surface((44 * ESCALA, 44 * ESCALA), pygame.SRCALPHA)
    pygame.draw.circle(s, (VERDE[0], VERDE[1], VERDE[2], 30),
                       (22 * ESCALA, 22 * ESCALA), 22 * ESCALA)
    tela.blit(s, ((REAL_W // 2 - 22) * ESCALA, (52 - 22) * ESCALA))
    pontos = [
        (cx - 10 * ESCALA, cy + 1 * ESCALA),
        (cx - 3 * ESCALA, cy + 9 * ESCALA),
        (cx + 12 * ESCALA, cy - 8 * ESCALA),
    ]
    pygame.draw.lines(tela, VERDE, False, pontos, 3 * ESCALA)
    tx(tela, "CONFIRMADO!", REAL_W // 2, 84, 13, VERDE, centro=True, bold=True)
    if med:
        nome = truncar(med["nome"], 16)
        tx(tela, nome, REAL_W // 2, 102, 11, BRANCO, centro=True, bold=True)
        tx(tela, f"Tomado as {datetime.now().strftime('%H:%M')}", REAL_W // 2, 116, 8, CINZA, centro=True)
    b = btn(tela, "VOLTAR", 24, 134, 80, 20, FUNDO_CARD_LIGHT, CINZA_ESCURO, mp, CINZA_CLARO, 6)
    return {"voltar": b}


def main():
    pygame.init()
    tela = pygame.display.set_mode((LARGURA, ALTURA))
    pygame.display.set_caption(f"Pinaid Pulseira {REAL_W}x{REAL_H}")
    try:
        icon = pygame.Surface((32, 32))
        icon.fill(AZUL)
        pygame.display.set_icon(icon)
    except:
        pass
    clock = pygame.time.Clock()
    threading.Thread(target=t_horarios, daemon=True).start()
    threading.Thread(target=t_realarme, daemon=True).start()
    print(f"{'=' * 40}")
    print(f"  PINAID Pulseira Mock {REAL_W}x{REAL_H} x{ESCALA}")
    print(f"  T = Testar alarme | S = Sync manual")
    print(f"{'=' * 40}")

    rodando = True
    while rodando:
        mp = pygame.mouse.get_pos()
        b = {}
        e.frame += 1

        if e.tela_foto_fullscreen:
            b = tela_foto_full(tela)
        elif e.tela == "inicio":
            b = tela_inicio(tela, mp)
        elif e.tela == "relogio":
            b = tela_relogio(tela, mp)
        elif e.tela == "alarme":
            b = tela_alarme(tela, mp)
        elif e.tela == "ok":
            b = tela_ok(tela, mp)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                rodando = False

            if e.tela_foto_fullscreen:
                if ev.type == pygame.MOUSEBUTTONDOWN or ev.type == pygame.KEYDOWN:
                    e.tela_foto_fullscreen = False
                continue

            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if "conectar" in b and b["conectar"].collidepoint(ev.pos):
                    if buscar():
                        e.tela = "relogio"
                if "sync" in b and b["sync"].collidepoint(ev.pos):
                    buscar()
                if "ja_vi" in b and b["ja_vi"].collidepoint(ev.pos):
                    e.vibrando = False
                    e.alarme_viu = True
                    e.alarme_inicio = datetime.now()
                if "ver_foto" in b and b["ver_foto"].collidepoint(ev.pos):
                    e.tela_foto_fullscreen = True
                if "tomei" in b and b["tomei"].collidepoint(ev.pos):
                    e.alarme_tomou = True
                    e.alarme_ativo = False
                    e.vibrando = False
                    e.tela_foto_fullscreen = False
                    confirmar(e.alarme_med)
                    e.tela = "ok"
                if "voltar" in b and b["voltar"].collidepoint(ev.pos):
                    e.tela = "relogio"
                    e.alarme_med = None
                    e.alarme_img = None
                    e.foto_fullscreen_surface = None

            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_t and e.agenda and not e.alarme_ativo:
                    m = e.agenda[0]
                    h = m["horario"][0] if isinstance(m["horario"], list) else m["horario"]
                    alarmar(m, h)
                if ev.key == pygame.K_s:
                    buscar()

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()