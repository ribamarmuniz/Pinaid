from flask import Flask, jsonify, send_from_directory, request, render_template
import json
import os
import re
from datetime import datetime

app = Flask(__name__)

PASTA_IMAGENS = "imagens_pulseira"
ARQUIVO_AGENDA = "agenda.json"
RASA_URL = "http://localhost:5005/webhooks/rest/webhook"
USAR_RASA = True  # Mude para False para usar sem Rasa

if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)


# =============================================
#  SESSAO PERSISTENTE
# =============================================

def obter_sessao():
    ag = carregar_agenda_db()
    s = ag.get("sessao", None)
    if not s:
        return {"fluxo": None, "etapa": None, "dados_temp": {}}
    return s


def salvar_sessao(sessao):
    ag = carregar_agenda_db()
    ag["sessao"] = sessao
    salvar_agenda_db(ag)


def limpar_sessao():
    salvar_sessao({"fluxo": None, "etapa": None, "dados_temp": {}})


def nome_paciente():
    pac = carregar_agenda_db().get("paciente", {})
    if pac.get("nome") and pac.get("confirmado"):
        return pac.get("nome")
    return None


def tratar():
    n = nome_paciente()
    return f"Sr(a). {n}" if n else "voce"


# =============================================
#  BANCO DE DADOS
# =============================================

def carregar_agenda_db():
    if os.path.exists(ARQUIVO_AGENDA):
        try:
            with open(ARQUIVO_AGENDA, "r", encoding="utf-8") as f:
                d = json.load(f)
                if "medicamentos" not in d: d["medicamentos"] = []
                if "configuracoes" not in d: d["configuracoes"] = {"horario_sono_inicio": "23:00", "horario_sono_fim": "07:00"}
                if "paciente" not in d: d["paciente"] = {"nome": "", "confirmado": False}
                return d
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "medicamentos": [],
        "configuracoes": {"horario_sono_inicio": "23:00", "horario_sono_fim": "07:00"},
        "paciente": {"nome": "", "confirmado": False},
    }


def salvar_agenda_db(dados):
    try:
        with open(ARQUIVO_AGENDA, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=4, ensure_ascii=False)
        return True
    except IOError:
        return False


# =============================================
#  HORARIOS
# =============================================

def validar_horario(h):
    return bool(re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", h))


def normalizar_horario(t):
    t = t.strip().lower()
    if re.match(r"^\d{2}:\d{2}$", t): return t if validar_horario(t) else None
    if re.match(r"^\d{1}:\d{2}$", t): return ("0"+t) if validar_horario("0"+t) else None
    m = re.match(r"^(\d{1,2})h(\d{0,2})$", t)
    if m:
        hh = m.group(1).zfill(2)
        mm = m.group(2).zfill(2) if m.group(2) else "00"
        r = f"{hh}:{mm}"
        return r if validar_horario(r) else None
    if re.match(r"^\d{4}$", t):
        r = t[:2] + ":" + t[2:]
        return r if validar_horario(r) else None
    return None


def hm(h):
    try:
        p = h.split(":")
        return int(p[0]) * 60 + int(p[1])
    except: return 0


def mh(m):
    m = m % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def no_sono(h, cfg):
    si = hm(cfg.get("horario_sono_inicio", "23:00"))
    sf = hm(cfg.get("horario_sono_fim", "07:00"))
    v = hm(h)
    return (v >= si or v < sf) if si > sf else (si <= v < sf)


def calcular_doses_dia(primeira, vezes, cfg, categoria="normal"):
    si = hm(cfg.get("horario_sono_inicio", "23:00"))
    ini = hm(primeira)
    limite = si - 60
    if limite < 0: limite += 1440
    if vezes == 1:
        h = mh(ini)
        if no_sono(h, cfg) and categoria == "normal":
             sf = hm(cfg.get("horario_sono_fim", "07:00"))
             novo = sf + 60
             return [mh(novo)], 0, [{"dose": 1, "tipo": "ajuste_sono", "horario": mh(novo), "msg": "Cairia no sono. Movida para acordar+1h"}]
        return [mh(ini)], 0, []
    espaco = (limite - ini) if limite > ini else (limite + 1440 - ini)
    iv_min = max(60, espaco // (vezes - 1))
    iv_real = iv_min
    iv_h = iv_real // 60
    hs = []
    conf = []
    minuto_atual = ini
    sf = hm(cfg.get("horario_sono_fim", "07:00"))
    acordar_min = sf + 60
    for i in range(vezes):
        min_dia = minuto_atual % 1440
        h = mh(min_dia)
        cai_sono = no_sono(h, cfg)
        if cai_sono and categoria == "normal":
            novo_minuto = acordar_min
            h_novo = mh(novo_minuto)
            conf.append({"dose": i + 1, "tipo": "ajuste_sono", "horario": h_novo, "msg": f"Dose {i+1} cairia no sono ({h}). Movida para {h_novo}."})
            minuto_atual = novo_minuto
            h = h_novo
        elif cai_sono and categoria == "essencial":
             conf.append({"dose": i + 1, "tipo": "sono_essencial", "horario": h, "msg": f"Dose {i + 1} cai no sono (ESSENCIAL - vai alarmar)"})
        elif i > 0 and minuto_atual >= 1440:
             conf.append({"dose": i + 1, "tipo": "info", "horario": h, "msg": "Passa da meia-noite"})
        hs.append(h)
        minuto_atual += iv_real
    return hs, iv_h, conf


def calcular_doses_intervalo(primeira, total_doses, intervalo_h, cfg, categoria="normal"):
    sf = hm(cfg.get("horario_sono_fim", "07:00"))
    acordar_mais_1h = sf + 60
    iv_real = intervalo_h * 60
    hs = []
    conf = []
    minuto_atual = hm(primeira)
    dia = 0
    for i in range(total_doses):
        while minuto_atual >= 1440:
            minuto_atual -= 1440
            dia += 1
        h = mh(minuto_atual)
        cai_no_sono = no_sono(h, cfg)
        if cai_no_sono and categoria == "normal":
            h_original = h
            novo_minuto = acordar_mais_1h
            if novo_minuto <= minuto_atual:
                novo_minuto += 1440
                dia += 1
            minuto_atual = novo_minuto % 1440
            h = mh(minuto_atual)
            dia_txt = f" (dia {dia + 1})" if dia > 0 else ""
            conf.append({"dose": i + 1, "tipo": "ajuste_sono", "horario": h, "horario_original": h_original, "msg": f"Dose {i + 1} cairia as {h_original}. Movida para {h}{dia_txt}"})
        elif cai_no_sono and categoria == "essencial":
            dia_txt = f" (dia {dia + 1})" if dia > 0 else ""
            conf.append({"dose": i + 1, "tipo": "sono_essencial", "horario": h, "msg": f"Dose {i + 1} as {h}{dia_txt} cai no sono (ESSENCIAL)"})
        dia_txt = f" (dia {dia + 1})" if dia > 0 else ""
        hs.append({"horario": h, "dia": dia, "dia_txt": dia_txt})
        minuto_atual += iv_real
    return hs, conf


def recalcular_proxima_dose(med, horario_real_str):
    intervalo = med.get("intervalo_horas")
    if not intervalo or intervalo >= 24:
        return None
    try:
        partes = horario_real_str.split(":")
        real_min = int(partes[0]) * 60 + int(partes[1])
        prox_min = real_min + (intervalo * 60)
        if prox_min >= 1440:
            return None
        return mh(prox_min)
    except:
        return None


# =============================================
#  AUXILIARES
# =============================================

def buscar_id(ag, idd):
    for m in ag.get("medicamentos", []):
        if m.get("id") == idd: return m
    return None


def buscar_nome(ag, n):
    nl = n.lower().strip()
    return [m for m in ag.get("medicamentos", []) if m["nome"].lower().strip() == nl]


def prox_id(ag):
    return max((m.get("id", 0) for m in ag.get("medicamentos", [])), default=0) + 1


def tem_dup(ag, n, h_lista):
    nl = n.lower().strip()
    for m in ag.get("medicamentos", []):
        if m["nome"].lower().strip() == nl:
            if m["horario"] == h_lista:
                return True
    return False


def fmt_med(m):
    st = "ATIVO" if m.get("ativo", True) else "PAUSADO"
    cat = m.get("categoria", "normal").upper()
    iv = m.get("intervalo_horas")
    ii = f" | A cada {iv}h" if iv and iv < 24 else ""
    horarios = m["horario"]
    if isinstance(horarios, list):
        h_str = ", ".join(horarios)
    else:
        h_str = horarios
    foto = " [FOTO]" if m.get("img_arquivo") else ""
    return f"ID {m['id']} | <b>{m['nome']}</b> | {h_str} | {m['dose']}{ii} | {cat} | {st}{foto}"


def fmt_lista(meds, titulo="MEDICAMENTOS CADASTRADOS"):
    if not meds:
        return "Nenhum medicamento cadastrado."
    mo = sorted(meds, key=lambda m: m.get("id", 0))
    ls = [f"<b>{titulo}:</b><br>"]
    for m in mo:
        ls.append(fmt_med(m))
    ls.append(f"<br>Total: <b>{len(meds)}</b> medicamento(s)")
    ls.append("<br>Digite <b>menu</b> para voltar ao menu principal.")
    return "<br>".join(ls)


def montar_dose(dados):
    qtd = dados.get("quantidade_dose", 1)
    tipo = dados.get("tipo_dose", "")
    dose = dados.get("dose", "")
    if tipo and dose:
        return f"{qtd} {tipo}(s) de {dose}"
    return dose or "nao informada"


def menu_texto():
    ag = carregar_agenda_db()
    total = len(ag.get("medicamentos", []))
    ativos = len([m for m in ag.get("medicamentos", []) if m.get("ativo", True)])
    cfg = ag.get("configuracoes", {})
    pac = tratar()
    sono = f"{cfg.get('horario_sono_inicio', '23:00')} - {cfg.get('horario_sono_fim', '07:00')}"
    return (
        f"<b>MENU PRINCIPAL</b><br>"
        f"Paciente: <b>{pac}</b><br>"
        f"Remedios: {total} ({ativos} ativos, {total - ativos} pausados)<br>"
        f"Horario de sono: {sono}<br><br>"
        "<b>1.</b> Cadastrar remedio<br>"
        "<b>2.</b> Listar remedios<br>"
        "<b>3.</b> Editar remedio<br>"
        "<b>4.</b> Remover remedio<br>"
        "<b>5.</b> Proximo remedio<br>"
        "<b>6.</b> Pausar ou reativar<br>"
        "<b>7.</b> Configurar sono<br>"
        "<b>8.</b> Cadastro por descricao<br>"
        "<b>9.</b> Buscar remedio<br>"
        "<b>0.</b> Ajuda<br>"
        "<b>h.</b> Historico de doses<br><br>"
        "Rapido: <b>Losartana 08:00 50mg</b><br>"
        "Outros: <b>status</b> | <b>limpar</b> | <b>historico</b>"
    )


# =============================================
#  EXTRACAO TEXTO LIVRE
# =============================================

def extrair_texto(texto):
    info = {"nome": None, "dose": None, "tipo_dose": None, "quantidade_dose": None,
            "intervalo_horas": None, "vezes_por_dia": None, "horario": None}
    tl = texto.lower()
    ignorar = {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das",
               "que", "e", "em", "no", "na", "com", "por", "para", "ao", "remedio",
               "medicamento", "tomar", "tomo", "toma", "preciso", "devo", "deve",
               "ser", "tem", "tenho", "meu", "minha", "cada", "vez", "vezes",
               "hora", "horas", "dia", "primeira", "segunda", "dose", "doses",
               "comprimido", "comprimidos", "capsula", "capsulas", "gotas", "gota",
               "ml", "mg", "mcg", "ele", "ela"}
    for p in texto.split():
        pl = re.sub(r"[^a-zA-ZáéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]", "", p)
        if len(pl) >= 3 and pl.lower() not in ignorar and not re.match(r"^\d", pl):
            info["nome"] = pl.capitalize()
            break
    m = re.search(r"(\d+)\s*(mg|ml|g|mcg|ui)", tl)
    if m:
        info["dose"] = f"{m.group(1)}{m.group(2)}"
    tipos = {"comprimido": "comprimido", "comprimidos": "comprimido",
             "capsula": "capsula", "capsulas": "capsula",
             "gota": "gotas", "gotas": "gotas", "colher": "colher",
             "injecao": "injecao"}
    for p, t in tipos.items():
        if p in tl:
            info["tipo_dose"] = t
            break
    m = re.search(r"(\d+)\s*(comprimido|capsul|gota|colher)", tl)
    if m:
        info["quantidade_dose"] = int(m.group(1))
    for pat in [r"(?:a\s+)?cada\s+(\d+)\s*(?:h|hora|horas)",
                r"de\s+(\d+)\s+em\s+\d+\s*(?:h|hora|horas)",
                r"por\s+(\d+)\s*(?:h|hora|horas)"]:
        m = re.search(pat, tl)
        if m:
            info["intervalo_horas"] = int(m.group(1))
            break
    for pat in [r"(\d+)\s*(?:vez|vezes)\s*(?:ao|por|no)\s*dia", r"(\d+)\s*x\s*(?:ao|por)?\s*dia"]:
        m = re.search(pat, tl)
        if m:
            info["vezes_por_dia"] = int(m.group(1))
            break
    if info["intervalo_horas"] and not info["vezes_por_dia"]:
        info["vezes_por_dia"] = max(1, 24 // info["intervalo_horas"])
    if info["vezes_por_dia"] and not info["intervalo_horas"] and info["vezes_por_dia"] > 1:
        info["intervalo_horas"] = 24 // info["vezes_por_dia"]
    for pat in [r"(?:primeira\s+dose|comecar|começar|a\s+partir)\s*(?:as|às|a)?\s*(\d{1,2})[h:](\d{0,2})",
                r"(?:dose|tomar)\s*(?:as|às)?\s*(\d{1,2})[h:](\d{0,2})",
                r"(?:as|às)\s*(\d{1,2})[h:](\d{0,2})"]:
        m = re.search(pat, tl)
        if m:
            hh = m.group(1).zfill(2)
            mm = m.group(2).zfill(2) if m.group(2) else "00"
            hr = f"{hh}:{mm}"
            if validar_horario(hr):
                info["horario"] = hr
                break
    if not info["horario"]:
        m = re.search(r"(\d{1,2})h\b", tl)
        if m:
            hh = m.group(1).zfill(2)
            hr = f"{hh}:00"
            if validar_horario(hr):
                info["horario"] = hr
    return info


# =============================================
#  HISTORICO DE DOSES
# =============================================

def formatar_historico():
    ag = carregar_agenda_db()
    meds = ag.get("medicamentos", [])
    pac = tratar()
    linhas = [f"<b>HISTORICO DE DOSES - {pac}</b><br>"]
    tem_historico = False
    for m in sorted(meds, key=lambda x: x["nome"]):
        hist = m.get("historico_doses", [])
        if not hist:
            continue
        tem_historico = True
        linhas.append(f"<b>{m['nome']}</b> ({m['dose']}):")
        ultimas = hist[-10:]
        for d in reversed(ultimas):
            prog = d.get("programado", "--:--")
            real = d.get("real", "--:--")
            data = d.get("data", "--/--")
            atraso = ""
            if prog != "--:--" and real != "--:--":
                try:
                    prog_min = int(prog.split(":")[0]) * 60 + int(prog.split(":")[1])
                    real_min = int(real.split(":")[0]) * 60 + int(real.split(":")[1])
                    diff = real_min - prog_min
                    if diff > 0: atraso = f" (atraso: {diff}min)"
                    elif diff < 0: atraso = f" (adiantado: {abs(diff)}min)"
                    else: atraso = " (no horario)"
                except (ValueError, IndexError): pass
            ajuste = ""
            if d.get("proxima_ajustada"):
                ajuste = f" -> Prox ajustada: {d['proxima_ajustada']}"
            linhas.append(f"  {data} | Prog: {prog} | Real: {real}{atraso}{ajuste}")
        linhas.append("")
    if not tem_historico:
        linhas.append("Nenhuma dose registrada ainda.")
        linhas.append("O historico aparece quando o paciente confirma doses na pulseira.")
    linhas.append("<br>Digite <b>menu</b> para voltar.")
    return "<br>".join(linhas)


# =============================================
#  FLUXO PACIENTE (COM TRAVA)
# =============================================

def fluxo_paciente(msg, sessao):
    etapa = sessao.get("etapa")
    ml = msg.strip()
    if etapa == "pedir_nome":
        if len(ml) < 2:
            return "Nome muito curto. Informe o <b>nome do paciente</b>:"
        sessao["dados_temp"]["nome_candidato"] = ml.capitalize()
        sessao["etapa"] = "confirmar_nome"
        salvar_sessao(sessao)
        return f"O nome do paciente e <b>{ml.capitalize()}</b>?<br><br>Digite <b>sim</b> para confirmar ou <b>editar</b> para corrigir."
    if etapa == "confirmar_nome":
        nome_temp = sessao["dados_temp"].get("nome_candidato", "")
        if ml.lower() in ["sim", "s", "ok", "confirmo"]:
            ag = carregar_agenda_db()
            ag["paciente"]["nome"] = nome_temp
            ag["paciente"]["confirmado"] = True
            salvar_agenda_db(ag)
            limpar_sessao()
            return f"Perfeito! Prazer em conhecer, <b>Sr(a). {nome_temp}</b>!<br>Configuracao concluida.<br><br>" + menu_texto()
        if ml.lower() in ["editar", "nao", "n", "corrigir"]:
            sessao["etapa"] = "pedir_nome"
            salvar_sessao(sessao)
            return "Ok. Qual e o <b>nome correto</b> do paciente?"
        return f"Nao entendi. O nome e <b>{nome_temp}</b>?<br>Digite <b>sim</b> ou <b>editar</b>."
    sessao["etapa"] = "pedir_nome"
    salvar_sessao(sessao)
    return "Bem-vindo ao <b>Pinaid</b>!<br><br>Antes de comecar, qual o <b>nome do paciente</b>?"


# =============================================
#  FLUXO CADASTRAR
# =============================================

def fluxo_cadastrar(msg, sessao):
    etapa = sessao["etapa"]
    dados = sessao["dados_temp"]
    ml = msg.strip()
    pac = tratar()

    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao()
        return "Cadastro cancelado.<br><br>" + menu_texto()

    if etapa == "texto_livre":
        info = extrair_texto(ml)
        for k, v in info.items():
            if v is not None:
                dados[k] = v
        sessao["etapa"] = "revisar_texto"
        salvar_sessao(sessao)
        return resumo_texto(dados)

    if etapa == "revisar_texto":
        if ml.lower() in ["sim", "s", "ok"]:
            return avancar_faltante(sessao)
        if ml.lower().startswith("editar"):
            return editar_campo_texto(ml, sessao)
        return "<b>sim</b> confirmar | <b>editar N</b> corrigir | <b>cancelar</b>"

    if etapa == "editar_campo_texto":
        return aplicar_edicao_texto(ml, sessao)

    if etapa == "nome":
        if len(ml) < 2:
            return f"{pac}, qual o <b>nome do remedio</b>?"
        dados["nome"] = ml.capitalize()
        sessao["etapa"] = "dose"
        salvar_sessao(sessao)
        return f"Remedio: <b>{dados['nome']}</b><br>Qual a <b>concentracao</b>? (ex: 500mg, 50mg)"

    if etapa == "dose":
        if len(ml) < 1:
            return "Informe a dose."
        dados["dose"] = ml
        sessao["etapa"] = "tipo_dose"
        salvar_sessao(sessao)
        return ("Qual a <b>forma farmaceutica</b>?<br>"
                "<b>1.</b> Comprimido<br><b>2.</b> Capsula<br><b>3.</b> Gotas<br>"
                "<b>4.</b> Liquido (ml)<br><b>5.</b> Injecao<br><b>6.</b> Outro")

    if etapa == "tipo_dose":
        tipos = {"1": "comprimido", "2": "capsula", "3": "gotas",
                 "4": "liquido (ml)", "5": "injecao", "6": "outro"}
        tipo = tipos.get(ml, ml.lower())
        dados["tipo_dose"] = tipo
        sessao["etapa"] = "quantidade_dose"
        salvar_sessao(sessao)
        return f"Quantas unidades de <b>{tipo}</b> por dose?"

    if etapa == "quantidade_dose":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Informe um numero."
        dados["quantidade_dose"] = int(nums[0])
        dados["dose_completa"] = montar_dose(dados)
        sessao["etapa"] = "primeira_dose"
        salvar_sessao(sessao)
        return f"Dose: <b>{dados['dose_completa']}</b><br><br>Horario da <b>primeira dose</b>?"

    if etapa == "primeira_dose":
        h = normalizar_horario(ml)
        if not h:
            return f"Horario <b>{ml}</b> invalido. Use HH:MM (ex: 08:00)"
        dados["horario"] = h
        sessao["etapa"] = "modo_dose"
        salvar_sessao(sessao)
        return (f"Primeira dose: <b>{h}</b><br><br>"
                "Como funciona esse remedio?<br><br>"
                "<b>1.</b> Doses por dia (distribuidas automaticamente)<br>"
                "<b>2.</b> Intervalo fixo entre doses (ex: a cada 8h)<br>")

    if etapa == "modo_dose":
        if ml == "1":
            dados["modo"] = "dia"
            sessao["etapa"] = "vezes_dia"
            salvar_sessao(sessao)
            return "Quantas <b>doses por dia</b>? (ex: 1, 2, 3)"
        elif ml == "2":
            dados["modo"] = "intervalo"
            sessao["etapa"] = "intervalo_fixo"
            salvar_sessao(sessao)
            return "Intervalo entre doses em <b>horas</b>? (ex: 8)"
        return "<b>1</b> = Doses por dia | <b>2</b> = Intervalo fixo"

    if etapa == "vezes_dia":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Numero (1, 2, 3...):"
        vezes = int(nums[0])
        if vezes < 1 or vezes > 12:
            return "Entre 1 e 12."
        dados["vezes_por_dia"] = vezes
        if vezes == 1:
            dados["intervalo_horas"] = 24
            sessao["etapa"] = "categoria"
            salvar_sessao(sessao)
            return f"1 dose as <b>{dados['horario']}</b><br><br>" + perg_cat()
        sessao["etapa"] = "categoria_pre_dia"
        salvar_sessao(sessao)
        return f"<b>{vezes} doses por dia</b><br><br>" + perg_cat()

    if etapa == "categoria_pre_dia":
        cats = {"1": "essencial", "essencial": "essencial", "2": "normal", "normal": "normal"}
        cat = cats.get(ml.lower())
        if not cat:
            return "<b>1.</b> Essencial | <b>2.</b> Normal"
        dados["categoria"] = cat
        vezes = dados["vezes_por_dia"]
        ag = carregar_agenda_db()
        cfg = ag.get("configuracoes", {})
        hs, iv, conf = calcular_doses_dia(dados["horario"], vezes, cfg, cat)
        dados["horarios_calculados"] = hs
        dados["intervalo_horas"] = iv
        dados["conflitos"] = conf
        si = cfg.get("horario_sono_inicio", "23:00")
        sf = cfg.get("horario_sono_fim", "07:00")
        ls = [f"<b>{vezes} doses/dia</b> ({cat.upper()}) | Intervalo: ~{iv}h", f"Sono: {si}-{sf}", ""]
        for i, h in enumerate(hs, 1):
            mk = ""
            for c in conf:
                if c["dose"] == i:
                    if c["tipo"] == "ajuste_sono": mk = f" [MOVIDA]"
                    elif c["tipo"] == "sono_essencial": mk = " [SONO - VAI ALARMAR]"
            ls.append(f"  {i}a dose: <b>{h}</b>{mk}")
        ls.append("")
        msgs = [c['msg'] for c in conf if c.get('msg')]
        if msgs:
            ls.append("<i>Avisos:</i>")
            for m_msg in msgs: ls.append(f"<i>- {m_msg}</i>")
        ls.append("")
        ls += ["<b>sim</b> confirmar | <b>2</b> mudar horario | <b>cancelar</b>"]
        sessao["etapa"] = "confirmar_dia"
        salvar_sessao(sessao)
        return "<br>".join(ls)

    if etapa == "confirmar_dia":
        if ml.lower() in ["sim", "s", "ok"]:
            sessao["etapa"] = "observacoes"
            salvar_sessao(sessao)
            return "Alguma <b>observacao</b>? (ex: Tomar em jejum)<br>Digite a obs ou <b>nao</b> para pular."
        elif ml == "2":
            sessao["etapa"] = "primeira_dose"
            salvar_sessao(sessao)
            return "Novo <b>horario</b>:"
        return "<b>sim</b> | <b>2</b> mudar horario | <b>cancelar</b>"

    if etapa == "intervalo_fixo":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Horas (ex: 8):"
        iv = int(nums[0])
        if iv < 1 or iv > 48:
            return "Entre 1 e 48 horas."
        dados["intervalo_horas"] = iv
        sessao["etapa"] = "total_doses"
        salvar_sessao(sessao)
        return f"A cada <b>{iv}h</b>. Quantas <b>doses no total</b>? (ex: 7)"

    if etapa == "total_doses":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Numero de doses:"
        total = int(nums[0])
        if total < 1 or total > 100:
            return "Entre 1 e 100."
        dados["total_doses"] = total
        sessao["etapa"] = "categoria_pre_intervalo"
        salvar_sessao(sessao)
        iv = dados["intervalo_horas"]
        dias = (total * iv) / 24
        return (f"<b>{total} doses</b> a cada <b>{iv}h</b> (~{dias:.1f} dias)<br><br>" + perg_cat())

    if etapa == "categoria_pre_intervalo":
        cats = {"1": "essencial", "essencial": "essencial", "2": "normal", "normal": "normal"}
        cat = cats.get(ml.lower())
        if not cat:
            return "<b>1.</b> Essencial | <b>2.</b> Normal"
        dados["categoria"] = cat
        ag = carregar_agenda_db()
        cfg = ag.get("configuracoes", {})
        hs, conf = calcular_doses_intervalo(dados["horario"], dados["total_doses"], dados["intervalo_horas"], cfg, cat)
        dados["horarios_intervalo"] = hs
        dados["conflitos"] = conf
        si = cfg.get("horario_sono_inicio", "23:00")
        sf = cfg.get("horario_sono_fim", "07:00")
        ls = [f"<b>{dados['total_doses']} doses</b> a cada <b>{dados['intervalo_horas']}h</b> ({cat.upper()})", f"Sono: {si}-{sf}", ""]
        for i, item in enumerate(hs, 1):
            h = item["horario"]
            dia_txt = item.get("dia_txt", "")
            mk = ""
            for c in conf:
                if c["dose"] == i:
                    if c["tipo"] == "ajuste_sono": mk = f" [MOVIDA - era {c.get('horario_original', '?')}]"
                    elif c["tipo"] == "sono_essencial": mk = " [SONO - VAI ALARMAR]"
            ls.append(f"  {i}a dose: <b>{h}</b>{dia_txt}{mk}")
        ls.append("")
        ls.append("<b>sim</b> confirmar | <b>cancelar</b>")
        sessao["etapa"] = "confirmar_intervalo"
        salvar_sessao(sessao)
        return "<br>".join(ls)

    if etapa == "confirmar_intervalo":
        if ml.lower() in ["sim", "s", "ok"]:
            sessao["etapa"] = "observacoes"
            salvar_sessao(sessao)
            return "Alguma <b>observacao</b>? (ex: Tomar em jejum)<br>Digite a obs ou <b>nao</b> para pular."
        limpar_sessao()
        return "Cancelado.<br><br>" + menu_texto()

    if etapa == "categoria":
        cats = {"1": "essencial", "essencial": "essencial", "2": "normal", "normal": "normal"}
        cat = cats.get(ml.lower())
        if not cat:
            return "<b>1.</b> Essencial | <b>2.</b> Normal"
        dados["categoria"] = cat
        sessao["etapa"] = "observacoes"
        salvar_sessao(sessao)
        return "Alguma <b>observacao</b>? (ex: Tomar em jejum)<br>Digite a obs ou <b>nao</b> para pular."

    if etapa == "observacoes":
        dados["observacoes"] = "" if ml.lower() in ["nao", "n", "sem", "pular"] else ml
        sessao["etapa"] = "foto"
        salvar_sessao(sessao)
        return ("Deseja anexar uma <b>foto da caixa do remedio</b>?<br><br>"
                "Use o botao de foto para enviar a imagem, ou digite <b>nao</b> para pular.")

    if etapa == "foto":
        if ml.lower() in ["nao", "n", "sem", "pular", "nenhuma"]:
            dados["foto_pendente"] = False
            sessao["etapa"] = "confirmar_final"
            salvar_sessao(sessao)
            return resumo_final(dados)
        return ("Use o botao de foto para enviar a imagem,<br>"
                "ou digite <b>nao</b> para pular.")

    if etapa == "foto_recebida":
        sessao["etapa"] = "confirmar_final"
        salvar_sessao(sessao)
        return resumo_final(dados)

    if etapa == "confirmar_final":
        if ml.lower() in ["sim", "s", "ok"]:
            return salvar_completo(dados)
        if ml.lower() in ["nao", "n", "cancelar"]:
            limpar_sessao()
            return "Cancelado.<br><br>" + menu_texto()
        return "<b>sim</b> | <b>cancelar</b>"

    return "Erro. Digite <b>cancelar</b>."


def perg_cat():
    return "<b>Categoria:</b><br><b>1.</b> Essencial (alarma SEMPRE)<br><b>2.</b> Normal (doses no sono movidas para acordar+1h)"


def resumo_texto(dados):
    ls = ["<b>Informacoes extraidas:</b><br>"]
    ls.append(f"1. Nome: <b>{dados.get('nome', '--')}</b>")
    ls.append(f"2. Concentracao: <b>{dados.get('dose', '--')}</b>")
    ls.append(f"3. Forma: <b>{dados.get('tipo_dose', '--')}</b>")
    ls.append(f"4. Qtd por dose: <b>{dados.get('quantidade_dose', '--')}</b>")
    ls.append(f"5. Primeira dose: <b>{dados.get('horario', '--')}</b>")
    ls.append(f"6. Doses/dia: <b>{dados.get('vezes_por_dia', '--')}</b>")
    iv = dados.get("intervalo_horas")
    ls.append(f"7. Intervalo: <b>{iv}h</b>" if iv else "7. Intervalo: <b>--</b>")
    ls += ["", "<b>sim</b> confirmar | <b>editar N</b> corrigir | <b>cancelar</b>"]
    return "<br>".join(ls)


def editar_campo_texto(ml, sessao):
    partes = ml.split()
    if len(partes) < 2: return "Ex: <b>editar 5</b>"
    try: n = int(partes[1])
    except ValueError: return "Numero."
    mapa = {1: ("nome", "nome"), 2: ("dose", "concentracao"), 3: ("tipo_dose", "forma"),
            4: ("quantidade_dose", "qtd por dose"), 5: ("horario", "horario primeira dose"),
            6: ("vezes_por_dia", "doses/dia"), 7: ("intervalo_horas", "intervalo (horas)")}
    if n not in mapa: return "1 a 7."
    sessao["dados_temp"]["editando"] = mapa[n][0]
    sessao["etapa"] = "editar_campo_texto"
    salvar_sessao(sessao)
    return f"Novo valor para <b>{mapa[n][1]}</b>:"


def aplicar_edicao_texto(ml, sessao):
    dados = sessao["dados_temp"]
    campo = dados.get("editando")
    if campo == "nome": dados["nome"] = ml.capitalize()
    elif campo == "dose": dados["dose"] = ml
    elif campo == "tipo_dose": dados["tipo_dose"] = ml.lower()
    elif campo == "quantidade_dose":
        nums = re.findall(r"\d+", ml)
        if not nums: return "Numero."
        dados["quantidade_dose"] = int(nums[0])
    elif campo == "horario":
        h = normalizar_horario(ml)
        if not h: return "Invalido."
        dados["horario"] = h
    elif campo == "vezes_por_dia":
        nums = re.findall(r"\d+", ml)
        if not nums: return "Numero."
        dados["vezes_por_dia"] = int(nums[0])
    elif campo == "intervalo_horas":
        nums = re.findall(r"\d+", ml)
        if not nums: return "Numero."
        dados["intervalo_horas"] = int(nums[0])
    sessao["etapa"] = "revisar_texto"
    salvar_sessao(sessao)
    return resumo_texto(dados)


def avancar_faltante(sessao):
    dados = sessao["dados_temp"]
    pac = tratar()
    if not dados.get("nome"):
        sessao["etapa"] = "nome"; salvar_sessao(sessao)
        return f"{pac}, <b>nome do remedio</b>?"
    if not dados.get("dose"):
        sessao["etapa"] = "dose"; salvar_sessao(sessao)
        return "<b>Concentracao</b>? (500mg)"
    if not dados.get("tipo_dose"):
        sessao["etapa"] = "tipo_dose"; salvar_sessao(sessao)
        return "<b>1.</b> Comprimido | <b>2.</b> Capsula | <b>3.</b> Gotas | <b>4.</b> Liquido | <b>5.</b> Injecao | <b>6.</b> Outro"
    if not dados.get("quantidade_dose"):
        sessao["etapa"] = "quantidade_dose"; salvar_sessao(sessao)
        return f"Quantas unidades de <b>{dados['tipo_dose']}</b> por dose?"
    if not dados.get("horario"):
        sessao["etapa"] = "primeira_dose"; salvar_sessao(sessao)
        return f"Horario da <b>primeira dose</b>?"
    if not dados.get("dose_completa"):
        dados["dose_completa"] = montar_dose(dados)
    sessao["etapa"] = "modo_dose"
    salvar_sessao(sessao)
    return ("Como funciona esse remedio?<br><br>"
            "<b>1.</b> Doses por dia (distribuidas automaticamente)<br>"
            "<b>2.</b> Intervalo fixo entre doses (pode passar de 1 dia)<br>")


def resumo_final(dados):
    modo = dados.get("modo", "dia")
    dc = dados.get("dose_completa") or montar_dose(dados)
    cat = dados.get("categoria", "normal")
    dados["dose_completa"] = dc
    ls = ["<b>RESUMO FINAL:</b><br>", f"Remedio: <b>{dados['nome']}</b>",
          f"Dose: <b>{dc}</b>", f"Categoria: <b>{cat.upper()}</b>"]
    if modo == "intervalo" and "horarios_intervalo" in dados:
        total = dados.get("total_doses", 0)
        iv = dados.get("intervalo_horas", 0)
        ls.append(f"Modo: <b>Intervalo fixo</b> | {total} doses a cada {iv}h")
        for i, item in enumerate(dados["horarios_intervalo"], 1):
            obs_dose = ""
            for c in dados.get("conflitos", []):
                if c["dose"] == i and c["tipo"] == "ajuste_sono": obs_dose = f" (movida)"
            ls.append(f"  {i}a: <b>{item['horario']}</b>{item.get('dia_txt', '')}{obs_dose}")
    else:
        vezes = dados.get("vezes_por_dia", 1)
        if vezes == 1:
            ls.append(f"Horario: <b>{dados['horario']}</b> (1x/dia)")
        else:
            ls.append(f"Modo: <b>Doses por dia</b> | {vezes}x/dia")
            for i, h in enumerate(dados.get("horarios_calculados", []), 1):
                ls.append(f"  {i}a dose: <b>{h}</b>")
    if dados.get("observacoes"):
        ls.append(f"Obs: <b>{dados['observacoes']}</b>")
    if dados.get("foto_arquivo"):
        ls.append(f"Foto: <b>{dados['foto_arquivo']}</b>")
    else:
        ls.append("Foto: <b>Nenhuma</b>")
    ls += ["", "<b>sim</b> confirmar | <b>cancelar</b>"]
    return "<br>".join(ls)


def salvar_completo(dados):
    ag = carregar_agenda_db()
    modo = dados.get("modo", "dia")
    iv = dados.get("intervalo_horas", 24)
    dc = dados.get("dose_completa") or montar_dose(dados)
    cat = dados.get("categoria", "normal")
    if modo == "intervalo" and "horarios_intervalo" in dados:
        hs = [item["horario"] for item in dados["horarios_intervalo"]]
        vezes = dados.get("total_doses", len(hs))
    else:
        vezes = dados.get("vezes_por_dia", 1)
        hs = dados.get("horarios_calculados", [dados["horario"]])
    if tem_dup(ag, dados["nome"], hs):
        limpar_sessao()
        return "Remedio ja cadastrado com esses horarios.<br><br>" + menu_texto()
    novo_id = prox_id(ag)
    foto_arquivo = ""
    foto_temp = dados.get("foto_arquivo", "")
    if foto_temp and os.path.exists(os.path.join(PASTA_IMAGENS, foto_temp)):
        ext = os.path.splitext(foto_temp)[1]
        foto_definitiva = f"{novo_id}{ext}"
        caminho_temp = os.path.join(PASTA_IMAGENS, foto_temp)
        caminho_def = os.path.join(PASTA_IMAGENS, foto_definitiva)
        try:
            os.rename(caminho_temp, caminho_def)
            foto_arquivo = foto_definitiva
        except Exception as err:
            print(f"Erro ao renomear foto: {err}")
            foto_arquivo = foto_temp
    med = {
        "id": novo_id, "nome": dados["nome"], "dose": dc,
        "tipo_dose": dados.get("tipo_dose", ""),
        "quantidade_dose": dados.get("quantidade_dose", 1),
        "horario": hs, "horario_original": hs[0] if hs else "",
        "intervalo_horas": iv if vezes > 1 else None,
        "vezes_por_dia": vezes, "modo": modo,
        "categoria": cat, "observacoes": dados.get("observacoes", ""),
        "ativo": True, "img_arquivo": foto_arquivo,
        "cadastrado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "historico_doses": [], "proxima_dose_ajustada": None,
    }
    ag["medicamentos"].append(med)
    salvar_agenda_db(ag)
    limpar_sessao()
    h_str = ", ".join(hs) if len(hs) > 1 else hs[0]
    foto_txt = " | Com foto" if foto_arquivo else ""
    ls = ["<b>CADASTRO REALIZADO!</b><br>"]
    ls.append(f"ID {med['id']} | <b>{med['nome']}</b> | {h_str} | {med['dose']} | {med['categoria'].upper()}{foto_txt}")
    ls.append(f"<br>Total: <b>{len(ag['medicamentos'])}</b><br>Digite <b>menu</b> para voltar.")
    return "<br>".join(ls)


# =============================================
#  FLUXO EDITAR
# =============================================

def fluxo_editar(msg, sessao):
    etapa = sessao["etapa"]
    dados = sessao["dados_temp"]
    ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao()
        return "Cancelado.<br><br>" + menu_texto()
    if etapa == "qual":
        ag = carregar_agenda_db()
        try:
            med = buscar_id(ag, int(ml))
            if med:
                dados["id"] = med["id"]
                dados["med"] = dict(med)
                sessao["etapa"] = "campo"
                salvar_sessao(sessao)
                h_display = med['horario']
                if isinstance(h_display, list): h_display = ", ".join(h_display)
                foto_txt = "Sim" if med.get("img_arquivo") else "Nenhuma"
                return (f"<b>Editando: {med['nome']}</b><br>"
                        f"<b>1.</b> Nome: {med['nome']}<br>"
                        f"<b>2.</b> Horario: {h_display}<br>"
                        f"<b>3.</b> Dose: {med['dose']}<br>"
                        f"<b>4.</b> Categoria: {med.get('categoria', 'normal')}<br>"
                        f"<b>5.</b> Obs: {med.get('observacoes', '(nenhuma)')}<br>"
                        f"<b>6.</b> Foto: {foto_txt}<br><br>"
                        "Qual? (1-6) ou <b>cancelar</b>")
            return f"ID {ml} nao encontrado."
        except ValueError:
            r = buscar_nome(ag, ml)
            if len(r) == 1:
                dados["id"] = r[0]["id"]; dados["med"] = dict(r[0])
                sessao["etapa"] = "campo"; salvar_sessao(sessao)
                return f"<b>{r[0]['nome']}</b><br>1.Nome | 2.Horario | 3.Dose | 4.Cat | 5.Obs | 6.Foto<br>Qual? ou <b>cancelar</b>"
            elif len(r) > 1:
                return "<br>".join(["Varios. ID:<br>"] + [fmt_med(m) for m in r])
            return f"<b>{ml}</b> nao encontrado."
    if etapa == "campo":
        mapa = {"1": "nome", "2": "horario", "3": "dose", "4": "categoria", "5": "observacoes", "6": "foto"}
        campo = mapa.get(ml)
        if not campo: return "1-6 ou <b>cancelar</b>."
        dados["campo"] = campo
        if campo == "foto":
            sessao["etapa"] = "valor_foto"; salvar_sessao(sessao)
            med = dados["med"]
            foto_atual = "Sim" if med.get("img_arquivo") else "Nenhuma"
            return (f"Foto atual: <b>{foto_atual}</b><br><br>"
                    "Use o botao de foto para enviar nova imagem,<br>"
                    "ou digite <b>remover</b> para remover a foto atual,<br>"
                    "ou <b>cancelar</b> para voltar.")
        sessao["etapa"] = "valor"; salvar_sessao(sessao)
        med = dados["med"]
        val_atual = med.get(campo, '')
        if isinstance(val_atual, list): val_atual = ", ".join(val_atual)
        if campo == "categoria":
            return f"Atual: <b>{med.get('categoria', 'normal')}</b><br><b>1.</b> Essencial | <b>2.</b> Normal"
        return f"Atual: <b>{val_atual}</b><br>Novo valor:"
    if etapa == "valor":
        campo = dados["campo"]
        ag = carregar_agenda_db()
        med = buscar_id(ag, dados["id"])
        if not med: limpar_sessao(); return "Nao encontrado."
        if campo == "nome": med["nome"] = ml.capitalize()
        elif campo == "horario":
            h = normalizar_horario(ml)
            if not h: return "Invalido (digite 1 horario unico para resetar)."
            med["horario"] = [h]; med["horario_original"] = h; med["proxima_dose_ajustada"] = None
        elif campo == "dose": med["dose"] = ml
        elif campo == "categoria":
            c = {"1": "essencial", "2": "normal"}.get(ml, ml.lower())
            if c not in ["essencial", "normal"]: return "<b>1.</b> Essencial | <b>2.</b> Normal"
            med["categoria"] = c
        elif campo == "observacoes":
            med["observacoes"] = "" if ml.lower() in ["limpar", "remover"] else ml
        med["editado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        salvar_agenda_db(ag); limpar_sessao()
        return f"<b>Editado!</b><br><br>Digite <b>menu</b> para voltar."
    if etapa == "valor_foto":
        if ml.lower() in ["remover", "limpar", "deletar"]:
            ag = carregar_agenda_db()
            med = buscar_id(ag, dados["id"])
            if med:
                if med.get("img_arquivo"):
                    caminho = os.path.join(PASTA_IMAGENS, med["img_arquivo"])
                    if os.path.exists(caminho):
                        try: os.remove(caminho)
                        except: pass
                med["img_arquivo"] = ""
                med["editado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                salvar_agenda_db(ag)
            limpar_sessao()
            return "<b>Foto removida!</b><br><br>Digite <b>menu</b> para voltar."
        if ml.lower() in ["cancelar", "sair", "voltar"]:
            limpar_sessao()
            return "Cancelado.<br><br>" + menu_texto()
        return ("Use o botao de foto para enviar nova imagem,<br>"
                "ou digite <b>remover</b> para remover a foto,<br>"
                "ou <b>cancelar</b> para voltar.")
    if etapa == "foto_editada":
        limpar_sessao()
        return "<b>Foto atualizada!</b><br><br>Digite <b>menu</b> para voltar."
    limpar_sessao()
    return "Erro.<br><br>" + menu_texto()


# =============================================
#  FLUXO REMOVER
# =============================================

def fluxo_remover(msg, sessao):
    etapa = sessao["etapa"]; ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao(); return "Cancelado.<br><br>" + menu_texto()
    if etapa == "qual":
        ag = carregar_agenda_db()
        try:
            med = buscar_id(ag, int(ml))
            if med:
                sessao["dados_temp"] = {"id": med["id"], "med": dict(med)}
                sessao["etapa"] = "confirmar"; salvar_sessao(sessao)
                return f"Remover <b>{med['nome']}</b>? <b>sim</b> ou <b>cancelar</b>"
            return f"ID {ml} nao encontrado."
        except ValueError:
            r = buscar_nome(ag, ml)
            if len(r) == 1:
                sessao["dados_temp"] = {"id": r[0]["id"], "med": dict(r[0])}
                sessao["etapa"] = "confirmar"; salvar_sessao(sessao)
                return f"Remover <b>{r[0]['nome']}</b>? <b>sim</b> ou <b>cancelar</b>"
            elif len(r) > 1:
                return "<br>".join(["Varios. ID:<br>"] + [fmt_med(m) for m in r])
            return f"<b>{ml}</b> nao encontrado."
    if etapa == "confirmar":
        if ml.lower() in ["sim", "s"]:
            ag = carregar_agenda_db()
            idd = sessao["dados_temp"]["id"]; info = sessao["dados_temp"]["med"]
            for m in ag["medicamentos"]:
                if m.get("id") == idd and m.get("img_arquivo"):
                    caminho = os.path.join(PASTA_IMAGENS, m["img_arquivo"])
                    if os.path.exists(caminho):
                        try: os.remove(caminho)
                        except: pass
            ag["medicamentos"] = [m for m in ag["medicamentos"] if m.get("id") != idd]
            salvar_agenda_db(ag); limpar_sessao()
            return f"<b>Removido:</b> {info['nome']}<br>Restam {len(ag['medicamentos'])}.<br><br>Digite <b>menu</b> para voltar."
        limpar_sessao(); return "Cancelado.<br><br>" + menu_texto()
    limpar_sessao(); return "Erro."


# =============================================
#  FLUXO SONO
# =============================================

def fluxo_sono(msg, sessao):
    ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao(); return "Cancelado.<br><br>" + menu_texto()
    if sessao["etapa"] == "inicio":
        h = normalizar_horario(ml)
        if not h: return "Invalido. Ex: 23:00"
        sessao["dados_temp"]["si"] = h; sessao["etapa"] = "fim"; salvar_sessao(sessao)
        return f"Dorme as <b>{h}</b>. Que horas <b>acorda</b>?"
    if sessao["etapa"] == "fim":
        h = normalizar_horario(ml)
        if not h: return "Invalido."
        ag = carregar_agenda_db()
        ag["configuracoes"]["horario_sono_inicio"] = sessao["dados_temp"]["si"]
        ag["configuracoes"]["horario_sono_fim"] = h
        salvar_agenda_db(ag); limpar_sessao()
        return f"<b>Sono:</b> {sessao['dados_temp']['si']} - {h}<br><br>Digite <b>menu</b> para voltar."
    limpar_sessao(); return "Erro."


# =============================================
#  FLUXO PAUSAR/REATIVAR
# =============================================

def fluxo_pr(msg, sessao):
    etapa = sessao["etapa"]; ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao(); return "Cancelado.<br><br>" + menu_texto()
    if etapa == "escolha":
        if ml == "1":
            sessao["etapa"] = "pausar"; salvar_sessao(sessao)
            ag = carregar_agenda_db()
            at = [m for m in ag.get("medicamentos", []) if m.get("ativo", True)]
            if not at: limpar_sessao(); return "Nenhum ativo.<br><br>" + menu_texto()
            return "<b>PAUSAR</b><br>ID:<br><br>" + "<br>".join([fmt_med(m) for m in at]) + "<br><br>ou <b>cancelar</b>"
        elif ml == "2":
            sessao["etapa"] = "reativar"; salvar_sessao(sessao)
            ag = carregar_agenda_db()
            pa = [m for m in ag.get("medicamentos", []) if not m.get("ativo", True)]
            if not pa: limpar_sessao(); return "Nenhum pausado.<br><br>" + menu_texto()
            return "<b>REATIVAR</b><br>ID:<br><br>" + "<br>".join([fmt_med(m) for m in pa]) + "<br><br>ou <b>cancelar</b>"
        return "<b>1.</b> Pausar | <b>2.</b> Reativar | <b>cancelar</b>"
    if etapa == "pausar":
        try: idd = int(ml)
        except ValueError: return "ID."
        ag = carregar_agenda_db(); med = buscar_id(ag, idd)
        if not med: return "Nao encontrado."
        med["ativo"] = False; med["pausado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        salvar_agenda_db(ag); limpar_sessao()
        return f"<b>Pausado:</b> {med['nome']}<br><br>Digite <b>menu</b> para voltar."
    if etapa == "reativar":
        try: idd = int(ml)
        except ValueError: return "ID."
        ag = carregar_agenda_db(); med = buscar_id(ag, idd)
        if not med: return "Nao encontrado."
        med["ativo"] = True
        if "pausado_em" in med: del med["pausado_em"]
        salvar_agenda_db(ag); limpar_sessao()
        return f"<b>Reativado:</b> {med['nome']}<br><br>Digite <b>menu</b> para voltar."
    limpar_sessao(); return "Erro."


# =============================================
#  DETECCAO E RESPOSTAS (FALLBACK SEM RASA)
# =============================================

def detectar(msg):
    ml = msg.lower().strip()
    for s in ["oi", "ola", "bom dia", "boa tarde", "boa noite", "hey", "eae"]:
        if ml == s or ml.startswith(s + " ") or ml.startswith(s + ","): return "saudacao"
    for a in ["obrigado", "obrigada", "valeu", "brigado", "vlw"]:
        if a in ml: return "agradecimento"
    if ml in ["menu", "inicio", "opcoes"]: return "menu"
    if ml in ["ajuda", "help", "?", "como funciona"]: return "ajuda"
    if ml in ["historico", "historico de doses", "doses tomadas", "registro"]: return "historico"
    if ml in ["sono", "dormir", "horario de sono", "configurar sono"]: return "sono"
    for p in ["adicionar", "cadastrar", "novo", "add", "incluir", "inserir"]:
        if ml == p or ml.startswith(p + " "): return "cadastrar"
    for i in ["remedio e", "tomar", "tomo", "preciso tomar", "medico receitou", "devo tomar", "tenho que tomar"]:
        if i in ml: return "texto_livre"
    if ml in ["listar", "lista", "ver", "agenda", "remedios", "meus remedios", "mostrar"]: return "listar"
    if ml in ["limpar", "apagar tudo", "resetar"]: return "limpar"
    if ml in ["status", "resumo"]: return "status"
    if ml in ["proximo", "proximo remedio", "qual o proximo"]: return "proximo"
    for p in ["remover", "deletar", "excluir", "apagar", "tirar"]:
        if ml == p or ml.startswith(p + " "): return "remover"
    for p in ["editar", "alterar", "mudar", "trocar"]:
        if ml == p or ml.startswith(p + " "): return "editar"
    for p in ["pausar", "parar", "suspender", "desativar"]:
        if ml == p or ml.startswith(p + " "): return "pausar"
    for p in ["reativar", "ativar", "retomar"]:
        if ml == p or ml.startswith(p + " "): return "reativar"
    for p in ["buscar", "procurar", "encontrar"]:
        if ml.startswith(p + " "): return "buscar"
    partes = msg.strip().split()
    if len(partes) >= 3 and normalizar_horario(partes[1]):
        return "cadastro_rapido"
    return "nao_entendido"


def resp_proximo():
    ag = carregar_agenda_db()
    at = [m for m in ag.get("medicamentos", []) if m.get("ativo", True)]
    if not at: return "Nenhum ativo.<br><br>Digite <b>menu</b> para voltar."
    agora = datetime.now().strftime("%H:%M")
    candidatos = []
    for m in at:
        hs = m.get("horario"); 
        if not isinstance(hs, list): hs = [hs]
        for h in hs:
            if h >= agora: candidatos.append((h, m))
    if candidatos:
        candidatos.sort(key=lambda x: x[0])
        h_prox, p = candidatos[0]
        obs = f"<br>Obs: {p['observacoes']}" if p.get("observacoes") else ""
        foto = "<br>Com foto anexada" if p.get("img_arquivo") else ""
        return (f"<b>PROXIMO REMEDIO:</b><br><b>{p['nome']}</b> as <b>{h_prox}</b><br>"
                f"Dose: {p['dose']}<br>Categoria: {p.get('categoria', 'normal').upper()}"
                f"{obs}{foto}<br><br>Digite <b>menu</b> para voltar.")
    else:
        todos_horarios = []
        for m in at:
            hs = m.get("horario"); 
            if not isinstance(hs, list): hs = [hs]
            for h in hs: todos_horarios.append((h, m))
        if todos_horarios:
            todos_horarios.sort(key=lambda x: x[0])
            h_prox, p = todos_horarios[0]
            return (f"<b>PROXIMO (AMANHA):</b><br><b>{p['nome']}</b> as <b>{h_prox}</b><br>"
                    f"Dose: {p['dose']}<br><br>Digite <b>menu</b> para voltar.")
    return "Nenhum agendamento encontrado."


def resp_buscar(msg):
    partes = msg.split()
    if len(partes) < 2: return "Ex: <b>buscar Losartana</b>"
    nome = " ".join(partes[1:])
    ag = carregar_agenda_db()
    r = buscar_nome(ag, nome)
    if not r: r = [m for m in ag.get("medicamentos", []) if nome.lower() in m["nome"].lower()]
    if not r: return f"Nenhum com <b>{nome}</b>.<br><br>Digite <b>menu</b> para voltar."
    return fmt_lista(r, f"RESULTADOS: '{nome.upper()}'")


def resp_rapido(msg):
    partes = msg.strip().split()
    nome = partes[0].capitalize()
    h = normalizar_horario(partes[1])
    dose = " ".join(partes[2:])
    if not h: return "Horario invalido."
    ag = carregar_agenda_db()
    if tem_dup(ag, nome, [h]):
        return f"<b>{nome}</b> ja cadastrado as <b>{h}</b>."
    novo_id = prox_id(ag)
    med = {
        "id": novo_id, "nome": nome, "dose": dose,
        "tipo_dose": "", "quantidade_dose": 1, "horario": [h],
        "horario_original": h, "intervalo_horas": None, "vezes_por_dia": 1, "modo": "dia",
        "categoria": "normal", "observacoes": "", "ativo": True, "img_arquivo": "",
        "cadastrado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "historico_doses": [], "proxima_dose_ajustada": None,
    }
    ag["medicamentos"].append(med); salvar_agenda_db(ag)
    s = obter_sessao()
    s["fluxo"] = "foto_rapido"; s["etapa"] = "perguntar"
    s["dados_temp"] = {"id": novo_id, "nome": nome}
    salvar_sessao(s)
    return (f"<b>Cadastro rapido realizado!</b><br>"
            f"ID {novo_id} | <b>{nome}</b> | {h} | {dose}<br><br>"
            f"Deseja anexar uma <b>foto da caixa</b> deste remedio?<br>"
            f"Use o botao de foto para enviar, ou digite <b>nao</b> para pular.")


def fluxo_foto_rapido(msg, sessao):
    etapa = sessao["etapa"]; ml = msg.strip(); dados = sessao["dados_temp"]
    if ml.lower() in ["cancelar", "sair", "voltar", "menu", "nao", "n", "sem", "pular"]:
        limpar_sessao()
        if ml.lower() in ["nao", "n", "sem", "pular"]:
            return f"Ok, sem foto.<br><br>Digite <b>menu</b> para voltar."
        return "Cancelado.<br><br>" + menu_texto()
    if etapa == "perguntar":
        return ("Use o botao de foto para enviar a imagem,<br>"
                "ou digite <b>nao</b> para pular.")
    if etapa == "foto_salva":
        limpar_sessao()
        return f"<b>Foto adicionada ao {dados.get('nome', 'remedio')}!</b><br><br>Digite <b>menu</b> para voltar."
    limpar_sessao()
    return "Erro.<br><br>" + menu_texto()


def atalho(n):
    if n == "1":
        s = obter_sessao(); s["fluxo"] = "cadastrar"; s["etapa"] = "nome"; s["dados_temp"] = {}; salvar_sessao(s)
        return f"<b>CADASTRAR REMEDIO</b><br><br>{tratar()}, qual o <b>nome do remedio</b>?<br>(<b>cancelar</b> para sair)"
    elif n == "2": return fmt_lista(carregar_agenda_db().get("medicamentos", []))
    elif n == "3":
        s = obter_sessao(); s["fluxo"] = "editar"; s["etapa"] = "qual"; s["dados_temp"] = {}; salvar_sessao(s)
        meds = carregar_agenda_db().get("medicamentos", [])
        if not meds: limpar_sessao(); return "Nenhum remedio.<br><br>" + menu_texto()
        return "<b>EDITAR</b><br>ID ou nome:<br>(<b>cancelar</b> para sair)<br><br>" + fmt_lista(meds)
    elif n == "4":
        s = obter_sessao(); s["fluxo"] = "remover"; s["etapa"] = "qual"; s["dados_temp"] = {}; salvar_sessao(s)
        meds = carregar_agenda_db().get("medicamentos", [])
        if not meds: limpar_sessao(); return "Nada para remover.<br><br>" + menu_texto()
        return "<b>REMOVER</b><br>ID ou nome:<br>(<b>cancelar</b> para sair)<br><br>" + fmt_lista(meds)
    elif n == "5": return resp_proximo()
    elif n == "6":
        s = obter_sessao(); s["fluxo"] = "pr"; s["etapa"] = "escolha"; s["dados_temp"] = {}; salvar_sessao(s)
        return "<b>PAUSAR / REATIVAR</b><br><br><b>1.</b> Pausar<br><b>2.</b> Reativar<br><br>ou <b>cancelar</b>"
    elif n == "7":
        s = obter_sessao(); s["fluxo"] = "sono"; s["etapa"] = "inicio"; s["dados_temp"] = {}; salvar_sessao(s)
        c = carregar_agenda_db().get("configuracoes", {})
        return f"<b>SONO</b><br>Atual: {c.get('horario_sono_inicio', '23:00')}-{c.get('horario_sono_fim', '07:00')}<br><br>Que horas <b>dorme</b>?<br>(<b>cancelar</b> para sair)"
    elif n == "8":
        s = obter_sessao(); s["fluxo"] = "cadastrar"; s["etapa"] = "texto_livre"; s["dados_temp"] = {}; salvar_sessao(s)
        return "<b>CADASTRO POR DESCRICAO</b><br><br>Descreva o remedio. Ex:<br>'Preciso tomar Dipirona 500mg, 2 comprimidos a cada 8h, primeira dose as 10h'<br><br>Escreva:<br>(<b>cancelar</b> para sair)"
    elif n == "9":
        s = obter_sessao(); s["fluxo"] = "buscar"; s["etapa"] = "nome"; s["dados_temp"] = {}; salvar_sessao(s)
        return "<b>BUSCAR</b><br>Nome do remedio:<br>(<b>cancelar</b> para sair)"
    elif n == "0":
        return ("<b>AJUDA - PINAID</b><br><br>"
                "<b>Cadastro guiado:</b> opcao 1<br>"
                "<b>Cadastro por descricao:</b> opcao 8<br>"
                "<b>Cadastro rapido:</b> Losartana 08:00 50mg<br><br>"
                "<b>Tipos de dose:</b><br>"
                "- <b>Doses por dia:</b> distribui entre primeira dose e 1h antes de dormir<br>"
                "- <b>Intervalo fixo:</b> a cada Xh, pode durar varios dias<br><br>"
                "<b>Categorias:</b><br>"
                "- Essencial: alarma SEMPRE, mesmo durante sono<br>"
                "- Normal: doses no sono movidas para 1h apos acordar<br><br>"
                "<b>Historico:</b> digite <b>h</b> ou <b>historico</b><br><br>"
                "Digite <b>menu</b> para voltar.")
    return None


# =============================================
#  PROCESSAMENTO PRINCIPAL
# =============================================

def processar(msg):
    ml = msg.strip()
    sessao = obter_sessao()

    pac = carregar_agenda_db().get("paciente", {})
    nome_ja_ok = pac.get("nome") and pac.get("confirmado")

    if not nome_ja_ok:
        if sessao["fluxo"] == "paciente":
            return fluxo_paciente(ml, sessao)
        else:
            sessao["fluxo"] = "paciente"; sessao["etapa"] = "pedir_nome"; sessao["dados_temp"] = {}
            salvar_sessao(sessao)
            if len(ml) > 2 and ml.lower() not in ["menu", "oi"]:
                return fluxo_paciente(ml, sessao)
            return "Bem-vindo ao <b>Pinaid</b>!<br><br>Antes de comecar, qual o <b>nome do paciente</b>?"

    if sessao["fluxo"] == "cadastrar": return fluxo_cadastrar(ml, sessao)
    elif sessao["fluxo"] == "editar": return fluxo_editar(ml, sessao)
    elif sessao["fluxo"] == "remover": return fluxo_remover(ml, sessao)
    elif sessao["fluxo"] == "sono": return fluxo_sono(ml, sessao)
    elif sessao["fluxo"] == "pr": return fluxo_pr(ml, sessao)
    elif sessao["fluxo"] == "foto_rapido": return fluxo_foto_rapido(ml, sessao)
    elif sessao["fluxo"] == "buscar":
        if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
            limpar_sessao(); return "Cancelado.<br><br>" + menu_texto()
        limpar_sessao(); return resp_buscar("buscar " + ml)

    if ml in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        r = atalho(ml)
        if r: return r
    if ml.lower() in ["h", "historico", "historico de doses", "doses tomadas"]:
        return formatar_historico()

    intent = detectar(ml)
    if intent == "saudacao": return menu_texto()
    elif intent == "agradecimento": return f"De nada, {tratar()}! <b>menu</b> para voltar."
    elif intent == "menu": return menu_texto()
    elif intent == "ajuda": return atalho("0")
    elif intent == "historico": return formatar_historico()
    elif intent == "sono": return atalho("7")
    elif intent == "cadastrar": return atalho("1")
    elif intent == "texto_livre":
        s = obter_sessao(); s["fluxo"] = "cadastrar"; s["etapa"] = "texto_livre"; s["dados_temp"] = {}; salvar_sessao(s)
        return fluxo_cadastrar(ml, s)
    elif intent == "listar": return atalho("2")
    elif intent == "limpar":
        ag = carregar_agenda_db(); qtd = len(ag.get("medicamentos", []))
        if qtd == 0: return "Ja vazia.<br><br>" + menu_texto()
        ag["medicamentos"] = []; salvar_agenda_db(ag)
        return f"<b>{qtd}</b> removido(s).<br><br>" + menu_texto()
    elif intent == "status":
        ag = carregar_agenda_db(); meds = ag.get("medicamentos", [])
        total = len(meds); ativos = len([m for m in meds if m.get("ativo", True)])
        c = ag.get("configuracoes", {})
        return (f"<b>STATUS</b><br>Paciente: {tratar()}<br>"
                f"Total: {total} | Ativos: {ativos} | Pausados: {total - ativos}<br>"
                f"Sono: {c.get('horario_sono_inicio', '23:00')}-{c.get('horario_sono_fim', '07:00')}<br>"
                f"Agora: {datetime.now().strftime('%H:%M')}<br><br>Digite <b>menu</b> para voltar.")
    elif intent == "proximo": return resp_proximo()
    elif intent == "remover":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao(); s["fluxo"] = "remover"; s["etapa"] = "qual"; s["dados_temp"] = {}; salvar_sessao(s)
            return fluxo_remover(" ".join(partes[1:]), s)
        return atalho("4")
    elif intent == "editar":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao(); s["fluxo"] = "editar"; s["etapa"] = "qual"; s["dados_temp"] = {}; salvar_sessao(s)
            return fluxo_editar(partes[1], s)
        return atalho("3")
    elif intent == "pausar":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao(); s["fluxo"] = "pr"; s["etapa"] = "pausar"; s["dados_temp"] = {}; salvar_sessao(s)
            return fluxo_pr(partes[1], s)
        return atalho("6")
    elif intent == "reativar":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao(); s["fluxo"] = "pr"; s["etapa"] = "reativar"; s["dados_temp"] = {}; salvar_sessao(s)
            return fluxo_pr(partes[1], s)
        return atalho("6")
    elif intent == "buscar": return resp_buscar(ml)
    elif intent == "cadastro_rapido": return resp_rapido(ml)
    else: return f"Nao entendi: <b>{ml}</b><br><br>Digite <b>menu</b> para opcoes."


# =============================================
#  ROTAS
# =============================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat_bot():
    """Rota principal do chat. Processa direto (usado pelo Rasa actions e fallback)."""
    d = request.json
    if not d or "message" not in d:
        return jsonify({"reply": "Vazia."}), 400
    return jsonify({"reply": processar(d["message"])})


@app.route("/chat_rasa", methods=["POST"])
def chat_rasa():
    """Rota que o frontend usa: envia para o Rasa, que chama /chat via action."""
    d = request.json
    if not d or "message" not in d:
        return jsonify({"reply": "Vazia."}), 400

    msg = d["message"]

    if USAR_RASA:
        try:
            import requests as req
            rasa_resp = req.post(
                RASA_URL,
                json={"sender": "web_user", "message": msg},
                timeout=10
            )
            if rasa_resp.status_code == 200:
                respostas = rasa_resp.json()
                if respostas and len(respostas) > 0:
                    # Concatena todas as respostas do Rasa
                    textos = []
                    for r in respostas:
                        if r.get("text"):
                            textos.append(r["text"])
                    if textos:
                        return jsonify({"reply": "<br>".join(textos)})
                # Se Rasa nao retornou nada, fallback direto
                return jsonify({"reply": processar(msg)})
            else:
                # Rasa retornou erro, fallback
                return jsonify({"reply": processar(msg)})
        except Exception as ex:
            print(f"Rasa indisponivel ({ex}), usando fallback direto")
            return jsonify({"reply": processar(msg)})
    else:
        return jsonify({"reply": processar(msg)})


@app.route("/upload_foto", methods=["POST"])
def upload_foto():
    if 'foto' not in request.files:
        return jsonify({"reply": "Nenhum arquivo enviado."}), 400
    arquivo = request.files['foto']
    if arquivo.filename == '':
        return jsonify({"reply": "Arquivo vazio."}), 400
    ext = os.path.splitext(arquivo.filename)[1].lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
        return jsonify({"reply": "Formato invalido. Use PNG, JPG, JPEG, GIF, BMP ou WEBP."}), 400
    sessao = obter_sessao()

    if sessao.get("fluxo") == "cadastrar" and sessao.get("etapa") == "foto":
        nome_temp = f"temp_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
        caminho = os.path.join(PASTA_IMAGENS, nome_temp)
        arquivo.save(caminho)
        sessao["dados_temp"]["foto_arquivo"] = nome_temp
        sessao["etapa"] = "foto_recebida"; salvar_sessao(sessao)
        reply = fluxo_cadastrar("foto_ok", sessao)
        return jsonify({"reply": f"<b>Foto anexada com sucesso!</b><br><br>{reply}"})

    if sessao.get("fluxo") == "editar" and sessao.get("etapa") == "valor_foto":
        med_id = sessao["dados_temp"].get("id")
        if not med_id: return jsonify({"reply": "Erro: ID do medicamento nao encontrado."}), 400
        nome_arquivo = f"{med_id}{ext}"
        caminho = os.path.join(PASTA_IMAGENS, nome_arquivo)
        ag = carregar_agenda_db(); med = buscar_id(ag, med_id)
        if med and med.get("img_arquivo"):
            antigo = os.path.join(PASTA_IMAGENS, med["img_arquivo"])
            if os.path.exists(antigo) and antigo != caminho:
                try: os.remove(antigo)
                except: pass
        arquivo.save(caminho)
        if med:
            med["img_arquivo"] = nome_arquivo
            med["editado_em"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            salvar_agenda_db(ag)
        sessao["etapa"] = "foto_editada"; salvar_sessao(sessao)
        reply = fluxo_editar("foto_ok", sessao)
        return jsonify({"reply": f"<b>Foto atualizada com sucesso!</b><br><br>{reply}"})

    if sessao.get("fluxo") == "foto_rapido" and sessao.get("etapa") == "perguntar":
        med_id = sessao["dados_temp"].get("id")
        if not med_id: return jsonify({"reply": "Erro: ID nao encontrado."}), 400
        nome_arquivo = f"{med_id}{ext}"
        caminho = os.path.join(PASTA_IMAGENS, nome_arquivo)
        arquivo.save(caminho)
        ag = carregar_agenda_db(); med = buscar_id(ag, med_id)
        if med: med["img_arquivo"] = nome_arquivo; salvar_agenda_db(ag)
        sessao["etapa"] = "foto_salva"; salvar_sessao(sessao)
        reply = fluxo_foto_rapido("foto_ok", sessao)
        return jsonify({"reply": f"<b>Foto adicionada!</b><br><br>{reply}"})

    return jsonify({"reply": "Nenhum cadastro aguardando foto. Inicie um cadastro primeiro."}), 400


@app.route("/api/agenda")
def api_agenda():
    ag = carregar_agenda_db()
    meds_ativos = []
    for m in ag.get("medicamentos", []):
        if not m.get("ativo", True): continue
        med_enviar = dict(m)
        if m.get("proxima_dose_ajustada"):
            med_enviar["horario"] = [m["proxima_dose_ajustada"]]
        if not med_enviar.get("img_arquivo"):
            for ext_busca in ["png", "jpg", "jpeg"]:
                fname = f"{m['id']}.{ext_busca}"
                if os.path.exists(os.path.join(PASTA_IMAGENS, fname)):
                    med_enviar["img_arquivo"] = fname; break
        meds_ativos.append(med_enviar)
    return jsonify({
        "configuracoes": ag.get("configuracoes", {}),
        "paciente": ag.get("paciente", {}),
        "medicamentos": meds_ativos,
    })


@app.route("/api/imagens/<path:f>")
def api_img(f):
    c = os.path.join(PASTA_IMAGENS, f)
    return send_from_directory(PASTA_IMAGENS, f) if os.path.exists(c) else (jsonify({"erro": "404"}), 404)


@app.route("/api/confirmar", methods=["POST"])
def api_confirmar():
    d = request.json
    if not d: return jsonify({"status": "erro"}), 400
    med_nome = d.get("medicamento", "?")
    horario_prog = d.get("horario", "--:--")
    horario_real = d.get("horario_real", "--:--")
    ag = carregar_agenda_db()
    for med in ag.get("medicamentos", []):
        horarios = med["horario"]
        if not isinstance(horarios, list): horarios = [horarios]
        if med["nome"] == med_nome and (horario_prog in horarios or med.get("proxima_dose_ajustada") == horario_prog):
            if "historico_doses" not in med: med["historico_doses"] = []
            registro = {"programado": horario_prog, "real": horario_real,
                        "data": datetime.now().strftime("%d/%m/%Y"), "proxima_ajustada": None}
            if med.get("modo") == "intervalo" or med.get("intervalo_horas"):
                 nova_proxima = recalcular_proxima_dose(med, horario_real)
                 if nova_proxima:
                     med["proxima_dose_ajustada"] = nova_proxima
                     registro["proxima_ajustada"] = nova_proxima
            med["historico_doses"].append(registro)
            salvar_agenda_db(ag); break
    return jsonify({"status": "ok", "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S")})


if __name__ == "__main__":
    print("=" * 40)
    print("  PINAID | http://127.0.0.1:5000")
    if USAR_RASA:
        print(f"  RASA   | {RASA_URL}")
    else:
        print("  RASA   | DESATIVADO (fallback direto)")
    print("=" * 40)
    app.run(host="0.0.0.0", port=5000, debug=True)