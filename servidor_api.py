from flask import Flask, jsonify, send_from_directory, request, render_template
import json
import os
import re
from datetime import datetime

app = Flask(__name__)

PASTA_IMAGENS = "imagens_pulseira"
ARQUIVO_AGENDA = "agenda.json"

if not os.path.exists(PASTA_IMAGENS):
    os.makedirs(PASTA_IMAGENS)


# =============================================
#  SESSAO
# =============================================

sessoes = {}


def obter_sessao():
    chave = "usuario_local"
    if chave not in sessoes:
        sessoes[chave] = {"fluxo": None, "etapa": None, "dados_temp": {}}
    return sessoes[chave]


def limpar_sessao():
    sessoes["usuario_local"] = {"fluxo": None, "etapa": None, "dados_temp": {}}


def nome_paciente():
    return carregar_agenda_db().get("paciente", {}).get("nome", "")


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
                if "medicamentos" not in d:
                    d["medicamentos"] = []
                if "configuracoes" not in d:
                    d["configuracoes"] = {"horario_sono_inicio": "23:00", "horario_sono_fim": "07:00"}
                if "paciente" not in d:
                    d["paciente"] = {"nome": ""}
                return d
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "medicamentos": [],
        "configuracoes": {"horario_sono_inicio": "23:00", "horario_sono_fim": "07:00"},
        "paciente": {"nome": ""},
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
    if re.match(r"^\d{2}:\d{2}$", t):
        return t if validar_horario(t) else None
    if re.match(r"^\d{1}:\d{2}$", t):
        t = "0" + t
        return t if validar_horario(t) else None
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
    p = h.split(":")
    return int(p[0]) * 60 + int(p[1])


def mh(m):
    m = m % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def no_sono(h, cfg):
    si = hm(cfg.get("horario_sono_inicio", "23:00"))
    sf = hm(cfg.get("horario_sono_fim", "07:00"))
    v = hm(h)
    return (v >= si or v < sf) if si > sf else (si <= v < sf)


def calcular_doses_dia(primeira, vezes, cfg):
    """
    Calcula horarios das doses distribuidas no periodo ACORDADO.
    Primeira dose no horario informado.
    Ultima dose 1 hora antes do sono.
    Distribui igualmente entre elas.
    """
    sono_inicio = hm(cfg.get("horario_sono_inicio", "23:00"))
    inicio = hm(primeira)

    # Margem: ultima dose 1h antes do sono
    limite = sono_inicio - 60
    if limite <= inicio:
        limite = sono_inicio

    if vezes == 1:
        return [primeira], 0, []

    # Periodo disponivel entre primeira dose e limite
    periodo = limite - inicio
    if periodo <= 0:
        periodo = (1440 - inicio) + limite

    # Intervalo entre doses
    intervalo_min = periodo // (vezes - 1)
    intervalo_h = intervalo_min // 60
    intervalo_sobra = intervalo_min % 60

    # Se intervalo for muito pequeno
    if intervalo_min < 60:
        return None, 0, [{"tipo": "impossivel",
            "msg": f"Nao e possivel encaixar {vezes} doses entre {primeira} e {mh(limite)}. Periodo muito curto."}]

    horarios = []
    conflitos = []

    for i in range(vezes):
        m = inicio + (intervalo_min * i)
        h = mh(m)

        if m >= 1440:
            conflitos.append({"dose": i + 1, "tipo": "extrapola", "horario": h})
        elif no_sono(h, cfg) and i > 0:
            conflitos.append({"dose": i + 1, "tipo": "sono", "horario": h})

        horarios.append(h)

    return horarios, intervalo_min, conflitos


def calcular_doses_continuo(primeira, intervalo_h, total_doses):
    """
    Calcula horarios para remedio de uso continuo.
    Ex: tomar 7 vezes a cada 8h (vai alem de 1 dia).
    Retorna lista de (dia, horario).
    """
    inicio = hm(primeira)
    doses = []

    for i in range(total_doses):
        minutos_total = inicio + (intervalo_h * 60 * i)
        dia = minutos_total // 1440
        horario = mh(minutos_total)
        doses.append({"dia": dia + 1, "horario": horario, "dose_num": i + 1})

    return doses


def validar_intervalo_manual(primeira, vezes, iv_h, cfg):
    inicio = hm(primeira)
    sono_inicio = hm(cfg.get("horario_sono_inicio", "23:00"))
    hs = []
    conf = []
    for i in range(vezes):
        m = inicio + (iv_h * 60 * i)
        h = mh(m)
        if m >= 1440:
            conf.append({"dose": i + 1, "tipo": "extrapola", "horario": h})
        elif no_sono(h, cfg) and i > 0:
            conf.append({"dose": i + 1, "tipo": "sono", "horario": h})
        elif m > sono_inicio and i > 0:
            conf.append({"dose": i + 1, "tipo": "sono", "horario": h})
        hs.append(h)
    return hs, conf


def recalcular_proxima_dose(med, horario_real_str):
    intervalo = med.get("intervalo_horas")
    if not intervalo or intervalo >= 24:
        return None
    partes = horario_real_str.split(":")
    real_min = int(partes[0]) * 60 + int(partes[1])
    prox_min = real_min + (intervalo * 60)
    if prox_min >= 1440:
        return None
    return mh(prox_min)


# =============================================
#  AUXILIARES
# =============================================

def buscar_id(ag, idd):
    for m in ag.get("medicamentos", []):
        if m.get("id") == idd:
            return m
    return None


def buscar_nome(ag, n):
    nl = n.lower().strip()
    return [m for m in ag.get("medicamentos", []) if m["nome"].lower().strip() == nl]


def prox_id(ag):
    return max((m.get("id", 0) for m in ag.get("medicamentos", [])), default=0) + 1


def tem_dup(ag, n, h):
    nl = n.lower().strip()
    return any(m["nome"].lower().strip() == nl and m["horario"] == h for m in ag.get("medicamentos", []))


def fmt_med(m):
    st = "ATIVO" if m.get("ativo", True) else "PAUSADO"
    cat = m.get("categoria", "normal").upper()
    iv = m.get("intervalo_horas")
    ii = f" | A cada {iv}h" if iv and iv < 24 else ""
    prox = m.get("proxima_dose_ajustada")
    ip = f" | Prox: {prox}" if prox else ""
    return f"ID {m['id']} | <b>{m['nome']}</b> | {m['horario']} | {m['dose']}{ii} | {cat} | {st}{ip}"


def fmt_lista(meds, titulo="MEDICAMENTOS CADASTRADOS"):
    if not meds:
        return "Nenhum medicamento cadastrado."
    mo = sorted(meds, key=lambda m: m.get("horario", ""))
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
            "intervalo_horas": None, "vezes_por_dia": None, "horario": None, "total_doses": None}
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

    # Total de doses: "7 vezes", "tomar 10 doses"
    m = re.search(r"(\d+)\s*(?:vez|vezes|doses)\s*(?:no\s+total)?", tl)
    if m:
        info["total_doses"] = int(m.group(1))

    # Vezes por dia
    for pat in [r"(\d+)\s*(?:vez|vezes)\s*(?:ao|por|no)\s*dia", r"(\d+)\s*x\s*(?:ao|por)?\s*dia"]:
        m = re.search(pat, tl)
        if m:
            info["vezes_por_dia"] = int(m.group(1))
            break

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
#  HISTORICO
# =============================================

def formatar_historico():
    ag = carregar_agenda_db()
    meds = ag.get("medicamentos", [])
    pac = tratar()
    ls = [f"<b>HISTORICO DE DOSES - {pac}</b><br>"]
    tem = False
    for m in sorted(meds, key=lambda x: x["nome"]):
        hist = m.get("historico_doses", [])
        if not hist:
            continue
        tem = True
        ls.append(f"<b>{m['nome']}</b> ({m['dose']}):")
        for d in reversed(hist[-10:]):
            prog = d.get("programado", "--:--")
            real = d.get("real", "--:--")
            data = d.get("data", "--/--")
            atraso = ""
            try:
                pp = prog.split(":")
                rp = real.split(":")
                diff = (int(rp[0]) * 60 + int(rp[1])) - (int(pp[0]) * 60 + int(pp[1]))
                if diff > 0:
                    atraso = f" (atraso: {diff}min)"
                elif diff < 0:
                    atraso = f" (adiantado: {abs(diff)}min)"
                else:
                    atraso = " (pontual)"
            except:
                pass
            aj = f" | Prox: {d['proxima_ajustada']}" if d.get("proxima_ajustada") else ""
            ls.append(f"  {data} | {prog} -> {real}{atraso}{aj}")
        ls.append("")
    if not tem:
        ls.append("Nenhuma dose registrada ainda.")
    ls.append("<br>Digite <b>menu</b> para voltar.")
    return "<br>".join(ls)


# =============================================
#  FLUXO PACIENTE
# =============================================

def fluxo_paciente(msg, sessao):
    ml = msg.strip()
    if len(ml) < 2:
        return "Por favor, informe o <b>nome do paciente</b>:"
    ag = carregar_agenda_db()
    ag["paciente"]["nome"] = ml.capitalize()
    salvar_agenda_db(ag)
    limpar_sessao()
    return f"Prazer, <b>Sr(a). {ml.capitalize()}</b>! Sou o assistente Pinaid.<br><br>" + menu_texto()


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

    # --- TEXTO LIVRE ---
    if etapa == "texto_livre":
        info = extrair_texto(ml)
        for k, v in info.items():
            if v is not None:
                dados[k] = v
        sessao["etapa"] = "revisar_texto"
        return resumo_texto(dados)

    if etapa == "revisar_texto":
        if ml.lower() in ["sim", "s", "ok"]:
            return avancar_faltante(sessao)
        if ml.lower().startswith("editar"):
            return editar_campo_texto(ml, sessao)
        return "<b>sim</b> confirmar | <b>editar N</b> corrigir | <b>cancelar</b>"

    if etapa == "editar_campo_texto":
        return aplicar_edicao_texto(ml, sessao)

    # --- NOME ---
    if etapa == "nome":
        if len(ml) < 2:
            return f"{pac}, qual o <b>nome do remedio</b>?"
        dados["nome"] = ml.capitalize()
        sessao["etapa"] = "dose"
        return f"Remedio: <b>{dados['nome']}</b><br>Qual a <b>concentracao</b>? (ex: 500mg)"

    # --- DOSE ---
    if etapa == "dose":
        if len(ml) < 1:
            return "Informe a dose."
        dados["dose"] = ml
        sessao["etapa"] = "tipo_dose"
        return (
            "Qual a <b>forma farmaceutica</b>?<br>"
            "<b>1.</b> Comprimido<br><b>2.</b> Capsula<br><b>3.</b> Gotas<br>"
            "<b>4.</b> Liquido (ml)<br><b>5.</b> Injecao<br><b>6.</b> Outro"
        )

    # --- TIPO ---
    if etapa == "tipo_dose":
        tipos = {"1": "comprimido", "2": "capsula", "3": "gotas",
                 "4": "liquido (ml)", "5": "injecao", "6": "outro"}
        tipo = tipos.get(ml, ml.lower())
        dados["tipo_dose"] = tipo
        sessao["etapa"] = "quantidade_dose"
        return f"Quantas unidades de <b>{tipo}</b> por dose?"

    # --- QUANTIDADE ---
    if etapa == "quantidade_dose":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Informe um numero."
        dados["quantidade_dose"] = int(nums[0])
        dados["dose_completa"] = montar_dose(dados)
        sessao["etapa"] = "tipo_remedio"
        return (
            f"Dose: <b>{dados['dose_completa']}</b><br><br>"
            "Qual o <b>tipo de uso</b> deste remedio?<br>"
            "<b>1.</b> Uso diario (X doses por dia, todos os dias)<br>"
            "<b>2.</b> Uso por intervalo fixo (a cada Xh, por Y doses no total)<br><br>"
            "Exemplo tipo 1: Losartana 2x ao dia<br>"
            "Exemplo tipo 2: Antibiotico a cada 8h por 21 doses"
        )

    # --- TIPO DE REMEDIO ---
    if etapa == "tipo_remedio":
        if ml in ["1", "diario"]:
            dados["modo_uso"] = "diario"
            sessao["etapa"] = "primeira_dose"
            return f"Horario da <b>primeira dose</b> do dia de {pac}?<br>(ex: 08:00, 8h)"
        elif ml in ["2", "intervalo", "continuo"]:
            dados["modo_uso"] = "continuo"
            sessao["etapa"] = "intervalo_continuo"
            return "De <b>quantas em quantas horas</b> deve tomar?<br>(ex: 4, 6, 8, 12)"
        return "<b>1.</b> Uso diario | <b>2.</b> Intervalo fixo"

    # --- INTERVALO CONTINUO ---
    if etapa == "intervalo_continuo":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Horas (4, 6, 8...):"
        dados["intervalo_horas"] = int(nums[0])
        sessao["etapa"] = "total_doses_continuo"
        return "Quantas <b>doses no total</b>?<br>(ex: 7, 10, 21)"

    # --- TOTAL DOSES CONTINUO ---
    if etapa == "total_doses_continuo":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Numero total de doses:"
        total = int(nums[0])
        dados["total_doses"] = total
        sessao["etapa"] = "primeira_dose_continuo"
        return f"<b>{total} doses</b> a cada <b>{dados['intervalo_horas']}h</b>.<br><br>Horario da <b>primeira dose</b>?"

    # --- PRIMEIRA DOSE CONTINUO ---
    if etapa == "primeira_dose_continuo":
        h = normalizar_horario(ml)
        if not h:
            return "Horario invalido."
        dados["horario"] = h
        iv = dados["intervalo_horas"]
        total = dados["total_doses"]

        doses = calcular_doses_continuo(h, iv, total)
        dados["doses_continuo"] = doses
        dados["vezes_por_dia"] = total

        dias_total = doses[-1]["dia"]

        ls = [f"<b>{total} doses a cada {iv}h</b>, a partir das <b>{h}</b>:", ""]
        for d in doses:
            ls.append(f"  Dia {d['dia']} - Dose {d['dose_num']}: <b>{d['horario']}</b>")
        ls.append("")
        ls.append(f"Total: <b>{dias_total} dia(s)</b>")
        ls.append("")
        ls.append("<b>sim</b> confirmar | <b>cancelar</b>")
        sessao["etapa"] = "categoria"

        dados["_preview_msg"] = "<br>".join(ls) + "<br><br>" + perg_cat()
        sessao["etapa"] = "confirmar_continuo"
        return "<br>".join(ls)

    # --- CONFIRMAR CONTINUO ---
    if etapa == "confirmar_continuo":
        if ml.lower() in ["sim", "s", "ok"]:
            sessao["etapa"] = "categoria"
            return perg_cat()
        if ml.lower() in ["cancelar", "nao", "n"]:
            limpar_sessao()
            return "Cancelado.<br><br>" + menu_texto()
        return "<b>sim</b> | <b>cancelar</b>"

    # --- PRIMEIRA DOSE (DIARIO) ---
    if etapa == "primeira_dose":
        h = normalizar_horario(ml)
        if not h:
            return f"Horario <b>{ml}</b> invalido."
        dados["horario"] = h
        sessao["etapa"] = "vezes_por_dia"
        return f"Primeira dose: <b>{h}</b><br>Quantas <b>doses por dia</b>?"

    # --- VEZES POR DIA ---
    if etapa == "vezes_por_dia":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Numero:"
        vezes = int(nums[0])
        if vezes < 1 or vezes > 12:
            return "Entre 1 e 12."
        dados["vezes_por_dia"] = vezes
        dados["modo_uso"] = "diario"

        if vezes == 1:
            dados["intervalo_horas"] = 24
            sessao["etapa"] = "categoria"
            return f"1 dose as <b>{dados['horario']}</b><br><br>" + perg_cat()

        ag = carregar_agenda_db()
        cfg = ag.get("configuracoes", {})
        hs, iv_min, conf = calcular_doses_dia(dados["horario"], vezes, cfg)

        if hs is None:
            return "<br>".join([c["msg"] for c in conf]) + "<br><br><b>3.</b> Mudar horario | <b>4.</b> Mudar doses | <b>cancelar</b>"

        dados["horarios_calculados"] = hs
        dados["intervalo_horas"] = iv_min // 60 if iv_min >= 60 else 1
        dados["intervalo_minutos"] = iv_min
        dados["conflitos"] = conf

        si = cfg.get("horario_sono_inicio", "23:00")
        sf = cfg.get("horario_sono_fim", "07:00")

        iv_h = iv_min // 60
        iv_m = iv_min % 60
        iv_txt = f"{iv_h}h" if iv_m == 0 else f"{iv_h}h{iv_m:02d}min"

        ls = [f"<b>{vezes} doses</b>, intervalo de <b>{iv_txt}</b>:",
              f"(Sono: {si} - {sf}, ultima dose 1h antes do sono)", ""]
        erro = False
        for i, h in enumerate(hs, 1):
            mk = ""
            for c in conf:
                if c["dose"] == i:
                    mk = "  [SONO]" if c["tipo"] == "sono" else "  [EXTRAPOLA]"
                    erro = True
            ls.append(f"  {i}a dose: <b>{h}</b>{mk}")
        ls.append("")
        if erro:
            ls += ["<b>Conflitos.</b>", "<b>1.</b> Aceitar | <b>2.</b> Mudar intervalo | <b>3.</b> Mudar horario | <b>4.</b> Mudar doses | <b>cancelar</b>"]
            sessao["etapa"] = "resolver"
        else:
            ls += ["<b>sim</b> confirmar | <b>2</b> mudar intervalo | <b>3</b> mudar horario"]
            sessao["etapa"] = "confirmar_hs"
        return "<br>".join(ls)

    # --- RESOLVER ---
    if etapa == "resolver":
        if ml in ["1", "sim"]:
            sessao["etapa"] = "categoria"
            return perg_cat()
        elif ml == "2":
            sessao["etapa"] = "intervalo_manual"
            return "<b>Intervalo em horas</b>:"
        elif ml == "3":
            sessao["etapa"] = "primeira_dose"
            return "Novo <b>horario</b>:"
        elif ml == "4":
            sessao["etapa"] = "vezes_por_dia"
            return "<b>Doses por dia</b>?"
        return "<b>1-4</b> ou <b>cancelar</b>"

    # --- CONFIRMAR HORARIOS ---
    if etapa == "confirmar_hs":
        if ml.lower() in ["sim", "s", "ok"]:
            sessao["etapa"] = "categoria"
            return perg_cat()
        elif ml == "2":
            sessao["etapa"] = "intervalo_manual"
            return "<b>Intervalo em horas</b>:"
        elif ml == "3":
            sessao["etapa"] = "primeira_dose"
            return "Novo <b>horario</b>:"
        return "<b>sim</b> | <b>2</b> | <b>3</b>"

    # --- INTERVALO MANUAL ---
    if etapa == "intervalo_manual":
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Horas:"
        iv = int(nums[0])
        vezes = dados["vezes_por_dia"]
        if iv * (vezes - 1) >= 24:
            return f"{vezes} doses a cada {iv}h = {iv * (vezes - 1)}h. Excede 24h."
        ag = carregar_agenda_db()
        cfg = ag.get("configuracoes", {})
        hs, conf = validar_intervalo_manual(dados["horario"], vezes, iv, cfg)
        dados["horarios_calculados"] = hs
        dados["intervalo_horas"] = iv
        dados["conflitos"] = conf
        si = cfg.get("horario_sono_inicio", "23:00")
        ls = [f"Intervalo <b>{iv}h</b>:", ""]
        erro = False
        for i, h in enumerate(hs, 1):
            mk = ""
            for c in conf:
                if c["dose"] == i:
                    mk = "  [SONO]" if c["tipo"] == "sono" else "  [EXTRAPOLA]"
                    erro = True
            ls.append(f"  {i}a dose: <b>{h}</b>{mk}")
        ls.append("")
        if erro:
            ls += ["<b>1.</b> Aceitar | <b>2.</b> Intervalo | <b>3.</b> Horario | <b>cancelar</b>"]
            sessao["etapa"] = "resolver"
        else:
            ls += ["<b>sim</b> | <b>2</b> intervalo"]
            sessao["etapa"] = "confirmar_hs"
        return "<br>".join(ls)

    # --- CATEGORIA ---
    if etapa == "categoria":
        cats = {"1": "essencial", "2": "normal"}
        cat = cats.get(ml.lower())
        if not cat:
            return "<b>1.</b> Essencial | <b>2.</b> Normal"
        dados["categoria"] = cat
        conf = dados.get("conflitos", [])
        ext = [c for c in conf if c.get("tipo") == "extrapola"]
        if ext:
            return "<b>ERRO:</b> Doses passam da meia-noite.<br><b>2.</b> Intervalo | <b>3.</b> Horario | <b>cancelar</b>"
        if [c for c in conf if c.get("tipo") == "sono"] and cat == "normal":
            dados["pular_sono"] = True
        sessao["etapa"] = "observacoes"
        return "Alguma <b>observacao</b>? (ex: Tomar em jejum)<br>Obs ou <b>nao</b> para pular."

    # --- OBSERVACOES ---
    if etapa == "observacoes":
        dados["observacoes"] = "" if ml.lower() in ["nao", "n", "sem", "pular"] else ml
        sessao["etapa"] = "confirmar_final"
        return resumo_final(dados)

    # --- CONFIRMAR FINAL ---
    if etapa == "confirmar_final":
        if ml.lower() in ["sim", "s", "ok"]:
            return salvar_completo(dados)
        if ml.lower() in ["nao", "n", "cancelar"]:
            limpar_sessao()
            return "Cancelado.<br><br>" + menu_texto()
        return "<b>sim</b> | <b>cancelar</b>"

    return "Erro. <b>cancelar</b>"


def perg_cat():
    return "<b>Categoria:</b><br><b>1.</b> Essencial (alarma durante sono)<br><b>2.</b> Normal (nao alarma durante sono)"


def resumo_texto(dados):
    ls = ["<b>Informacoes extraidas:</b><br>"]
    ls.append(f"1. Nome: <b>{dados.get('nome', '--')}</b>")
    ls.append(f"2. Concentracao: <b>{dados.get('dose', '--')}</b>")
    ls.append(f"3. Forma: <b>{dados.get('tipo_dose', '--')}</b>")
    ls.append(f"4. Qtd/dose: <b>{dados.get('quantidade_dose', '--')}</b>")
    ls.append(f"5. Primeira dose: <b>{dados.get('horario', '--')}</b>")
    ls.append(f"6. Doses/dia: <b>{dados.get('vezes_por_dia', '--')}</b>")
    iv = dados.get("intervalo_horas")
    ls.append(f"7. Intervalo: <b>{iv}h</b>" if iv else "7. Intervalo: <b>--</b>")
    ls += ["", "<b>sim</b> | <b>editar N</b> | <b>cancelar</b>"]
    return "<br>".join(ls)


def editar_campo_texto(ml, sessao):
    partes = ml.split()
    if len(partes) < 2:
        return "Ex: <b>editar 5</b>"
    try:
        n = int(partes[1])
    except ValueError:
        return "Numero."
    mapa = {1: ("nome", "nome"), 2: ("dose", "concentracao"), 3: ("tipo_dose", "forma"),
            4: ("quantidade_dose", "qtd/dose"), 5: ("horario", "horario"),
            6: ("vezes_por_dia", "doses/dia"), 7: ("intervalo_horas", "intervalo (h)")}
    if n not in mapa:
        return "1 a 7."
    sessao["dados_temp"]["editando"] = mapa[n][0]
    sessao["etapa"] = "editar_campo_texto"
    return f"Novo valor para <b>{mapa[n][1]}</b>:"


def aplicar_edicao_texto(ml, sessao):
    dados = sessao["dados_temp"]
    campo = dados.get("editando")
    if campo == "nome":
        dados["nome"] = ml.capitalize()
    elif campo == "dose":
        dados["dose"] = ml
    elif campo == "tipo_dose":
        dados["tipo_dose"] = ml.lower()
    elif campo in ["quantidade_dose", "vezes_por_dia", "intervalo_horas"]:
        nums = re.findall(r"\d+", ml)
        if not nums:
            return "Numero."
        dados[campo] = int(nums[0])
    elif campo == "horario":
        h = normalizar_horario(ml)
        if not h:
            return "Invalido."
        dados["horario"] = h
    sessao["etapa"] = "revisar_texto"
    return resumo_texto(dados)


def avancar_faltante(sessao):
    dados = sessao["dados_temp"]
    pac = tratar()
    if not dados.get("nome"):
        sessao["etapa"] = "nome"
        return f"{pac}, <b>nome do remedio</b>?"
    if not dados.get("dose"):
        sessao["etapa"] = "dose"
        return "<b>Concentracao</b>?"
    if not dados.get("tipo_dose"):
        sessao["etapa"] = "tipo_dose"
        return "<b>1.</b> Comprimido | <b>2.</b> Capsula | <b>3.</b> Gotas | <b>4.</b> Liquido | <b>5.</b> Injecao | <b>6.</b> Outro"
    if not dados.get("quantidade_dose"):
        sessao["etapa"] = "quantidade_dose"
        return f"Quantas unidades de <b>{dados['tipo_dose']}</b> por dose?"
    if not dados.get("dose_completa"):
        dados["dose_completa"] = montar_dose(dados)

    # Se tem intervalo mas nao tem vezes/dia, e uso continuo
    if dados.get("intervalo_horas") and not dados.get("vezes_por_dia"):
        dados["modo_uso"] = "continuo"
        if not dados.get("total_doses"):
            sessao["etapa"] = "total_doses_continuo"
            return f"A cada <b>{dados['intervalo_horas']}h</b>. Quantas <b>doses no total</b>?"

    if not dados.get("horario"):
        sessao["etapa"] = "primeira_dose" if dados.get("modo_uso") != "continuo" else "primeira_dose_continuo"
        return f"Horario da <b>primeira dose</b>?"
    if not dados.get("vezes_por_dia") and not dados.get("total_doses"):
        sessao["etapa"] = "tipo_remedio"
        return (
            "Tipo de uso:<br>"
            "<b>1.</b> Diario (X doses por dia)<br>"
            "<b>2.</b> Intervalo fixo (a cada Xh por Y doses)"
        )
    if dados.get("modo_uso") == "continuo" and dados.get("total_doses"):
        sessao["etapa"] = "categoria"
        return perg_cat()
    if dados.get("vezes_por_dia") and dados["vezes_por_dia"] > 1:
        sessao["etapa"] = "vezes_por_dia"
        return fluxo_cadastrar(str(dados["vezes_por_dia"]), sessao)
    sessao["etapa"] = "categoria"
    return perg_cat()


def resumo_final(dados):
    vezes = dados.get("vezes_por_dia", 1)
    iv = dados.get("intervalo_horas", 24)
    dc = dados.get("dose_completa") or montar_dose(dados)
    dados["dose_completa"] = dc
    ls = ["<b>RESUMO FINAL:</b><br>", f"Remedio: <b>{dados['nome']}</b>",
          f"Dose: <b>{dc}</b>", f"Categoria: <b>{dados.get('categoria', 'normal').upper()}</b>"]

    if dados.get("modo_uso") == "continuo":
        total = dados.get("total_doses", vezes)
        ls.append(f"Modo: <b>Intervalo fixo, a cada {iv}h, {total} doses</b>")
        doses = dados.get("doses_continuo", [])
        for d in doses:
            ls.append(f"  Dia {d['dia']} - Dose {d['dose_num']}: <b>{d['horario']}</b>")
    elif vezes == 1:
        ls.append(f"Horario: <b>{dados['horario']}</b> (1x/dia)")
    else:
        ls.append(f"Frequencia: <b>{vezes}x/dia</b>")
        for i, h in enumerate(dados.get("horarios_calculados", []), 1):
            ls.append(f"  {i}a dose: <b>{h}</b>")
    if dados.get("pular_sono"):
        ls.append("Doses no sono serao puladas.")
    if dados.get("observacoes"):
        ls.append(f"Obs: <b>{dados['observacoes']}</b>")
    ls += ["", "<b>sim</b> confirmar | <b>cancelar</b>"]
    return "<br>".join(ls)


def salvar_completo(dados):
    ag = carregar_agenda_db()
    cfg = ag.get("configuracoes", {})
    dc = dados.get("dose_completa") or montar_dose(dados)
    iv = dados.get("intervalo_horas")

    if dados.get("modo_uso") == "continuo":
        doses = dados.get("doses_continuo", [])
        horarios = [d["horario"] for d in doses]
    else:
        vezes = dados.get("vezes_por_dia", 1)
        horarios = dados.get("horarios_calculados", [dados["horario"]]) if vezes > 1 else [dados["horario"]]

    criados = []
    for h in horarios:
        if dados.get("pular_sono") and no_sono(h, cfg):
            continue
        if tem_dup(ag, dados["nome"], h):
            continue
        med = {
            "id": prox_id(ag), "nome": dados["nome"], "dose": dc,
            "tipo_dose": dados.get("tipo_dose", ""), "quantidade_dose": dados.get("quantidade_dose", 1),
            "horario": h, "horario_original": h,
            "intervalo_horas": iv if iv and iv < 24 else None,
            "vezes_por_dia": dados.get("vezes_por_dia", 1),
            "modo_uso": dados.get("modo_uso", "diario"),
            "categoria": dados.get("categoria", "normal"),
            "observacoes": dados.get("observacoes", ""), "ativo": True, "img_arquivo": "",
            "cadastrado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "historico_doses": [], "proxima_dose_ajustada": None,
        }
        ag["medicamentos"].append(med)
        criados.append(med)
    if not criados:
        limpar_sessao()
        return "Nenhuma dose cadastrada.<br><br>" + menu_texto()
    salvar_agenda_db(ag)
    limpar_sessao()
    ls = ["<b>CADASTRO REALIZADO!</b><br>"]
    for m in criados:
        ls.append(f"ID {m['id']} | <b>{m['nome']}</b> | {m['horario']} | {m['dose']}")
    ls.append(f"<br>Total: <b>{len(ag['medicamentos'])}</b><br>Digite <b>menu</b> para voltar.")
    return "<br>".join(ls)


# =============================================
#  FLUXOS EDITAR, REMOVER, SONO, PAUSAR
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
                return (
                    f"<b>Editando: {med['nome']}</b><br>"
                    f"<b>1.</b> Nome: {med['nome']}<br>"
                    f"<b>2.</b> Horario: {med['horario']}<br>"
                    f"<b>3.</b> Dose: {med['dose']}<br>"
                    f"<b>4.</b> Categoria: {med.get('categoria', 'normal')}<br>"
                    f"<b>5.</b> Obs: {med.get('observacoes', '(nenhuma)')}<br><br>"
                    "Qual? (1-5) ou <b>cancelar</b>"
                )
            return "Nao encontrado."
        except ValueError:
            r = buscar_nome(ag, ml)
            if len(r) == 1:
                dados["id"] = r[0]["id"]
                dados["med"] = dict(r[0])
                sessao["etapa"] = "campo"
                return f"<b>{r[0]['nome']}</b><br>1-5? ou <b>cancelar</b>"
            elif len(r) > 1:
                return "<br>".join(["Varios. ID:<br>"] + [fmt_med(m) for m in r])
            return "Nao encontrado."
    if etapa == "campo":
        mapa = {"1": "nome", "2": "horario", "3": "dose", "4": "categoria", "5": "observacoes"}
        campo = mapa.get(ml)
        if not campo:
            return "1-5 ou <b>cancelar</b>."
        dados["campo"] = campo
        sessao["etapa"] = "valor"
        med = dados["med"]
        if campo == "categoria":
            return f"Atual: <b>{med.get('categoria', 'normal')}</b><br><b>1.</b> Essencial | <b>2.</b> Normal"
        return f"Atual: <b>{med.get(campo, '')}</b><br>Novo valor:"
    if etapa == "valor":
        campo = dados["campo"]
        ag = carregar_agenda_db()
        med = buscar_id(ag, dados["id"])
        if not med:
            limpar_sessao()
            return "Nao encontrado."
        antigo = med.get(campo, "")
        if campo == "nome":
            med["nome"] = ml.capitalize()
        elif campo == "horario":
            h = normalizar_horario(ml)
            if not h:
                return "Invalido."
            med["horario"] = h
            med["horario_original"] = h
            med["proxima_dose_ajustada"] = None
        elif campo == "dose":
            med["dose"] = ml
        elif campo == "categoria":
            c = {"1": "essencial", "2": "normal"}.get(ml, ml.lower())
            if c not in ["essencial", "normal"]:
                return "<b>1.</b> Essencial | <b>2.</b> Normal"
            med["categoria"] = c
        elif campo == "observacoes":
            med["observacoes"] = "" if ml.lower() in ["limpar", "remover"] else ml
        salvar_agenda_db(ag)
        limpar_sessao()
        return f"<b>Editado!</b> {campo}: {antigo} -> <b>{med.get(campo, ml)}</b><br><br>Digite <b>menu</b> para voltar."
    limpar_sessao()
    return "Erro.<br><br>" + menu_texto()


def fluxo_remover(msg, sessao):
    ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao()
        return "Cancelado.<br><br>" + menu_texto()
    if sessao["etapa"] == "qual":
        ag = carregar_agenda_db()
        try:
            med = buscar_id(ag, int(ml))
            if med:
                sessao["dados_temp"] = {"id": med["id"], "med": dict(med)}
                sessao["etapa"] = "confirmar"
                return f"Remover <b>{med['nome']}</b> ({med['horario']})? <b>sim</b> ou <b>cancelar</b>"
            return "Nao encontrado."
        except ValueError:
            r = buscar_nome(ag, ml)
            if len(r) == 1:
                sessao["dados_temp"] = {"id": r[0]["id"], "med": dict(r[0])}
                sessao["etapa"] = "confirmar"
                return f"Remover <b>{r[0]['nome']}</b>? <b>sim</b>/<b>cancelar</b>"
            elif len(r) > 1:
                return "<br>".join(["Varios. ID:<br>"] + [fmt_med(m) for m in r])
            return "Nao encontrado."
    if sessao["etapa"] == "confirmar":
        if ml.lower() in ["sim", "s"]:
            ag = carregar_agenda_db()
            idd = sessao["dados_temp"]["id"]
            info = sessao["dados_temp"]["med"]
            ag["medicamentos"] = [m for m in ag["medicamentos"] if m.get("id") != idd]
            salvar_agenda_db(ag)
            limpar_sessao()
            return f"<b>Removido:</b> {info['nome']}<br><br>Digite <b>menu</b> para voltar."
        limpar_sessao()
        return "Cancelado.<br><br>" + menu_texto()
    limpar_sessao()
    return "Erro."


def fluxo_sono(msg, sessao):
    ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao()
        return "Cancelado.<br><br>" + menu_texto()
    if sessao["etapa"] == "inicio":
        h = normalizar_horario(ml)
        if not h:
            return "Invalido."
        sessao["dados_temp"]["si"] = h
        sessao["etapa"] = "fim"
        return f"Dorme as <b>{h}</b>. Que horas <b>acorda</b>?"
    if sessao["etapa"] == "fim":
        h = normalizar_horario(ml)
        if not h:
            return "Invalido."
        ag = carregar_agenda_db()
        ag["configuracoes"]["horario_sono_inicio"] = sessao["dados_temp"]["si"]
        ag["configuracoes"]["horario_sono_fim"] = h
        salvar_agenda_db(ag)
        limpar_sessao()
        return f"<b>Sono:</b> {sessao['dados_temp']['si']} - {h}<br><br>Digite <b>menu</b> para voltar."
    limpar_sessao()
    return "Erro."


def fluxo_pr(msg, sessao):
    etapa = sessao["etapa"]
    ml = msg.strip()
    if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
        limpar_sessao()
        return "Cancelado.<br><br>" + menu_texto()
    if etapa == "escolha":
        if ml == "1":
            sessao["etapa"] = "pausar"
            ag = carregar_agenda_db()
            at = [m for m in ag.get("medicamentos", []) if m.get("ativo", True)]
            if not at:
                limpar_sessao()
                return "Nenhum ativo.<br><br>" + menu_texto()
            return "<b>PAUSAR</b><br>ID:<br><br>" + "<br>".join([fmt_med(m) for m in at]) + "<br><br><b>cancelar</b>"
        elif ml == "2":
            sessao["etapa"] = "reativar"
            ag = carregar_agenda_db()
            pa = [m for m in ag.get("medicamentos", []) if not m.get("ativo", True)]
            if not pa:
                limpar_sessao()
                return "Nenhum pausado.<br><br>" + menu_texto()
            return "<b>REATIVAR</b><br>ID:<br><br>" + "<br>".join([fmt_med(m) for m in pa]) + "<br><br><b>cancelar</b>"
        return "<b>1.</b> Pausar | <b>2.</b> Reativar"
    if etapa == "pausar":
        try:
            idd = int(ml)
        except ValueError:
            return "ID."
        ag = carregar_agenda_db()
        med = buscar_id(ag, idd)
        if not med:
            return "Nao encontrado."
        med["ativo"] = False
        salvar_agenda_db(ag)
        limpar_sessao()
        return f"<b>Pausado:</b> {med['nome']}<br><br>Digite <b>menu</b> para voltar."
    if etapa == "reativar":
        try:
            idd = int(ml)
        except ValueError:
            return "ID."
        ag = carregar_agenda_db()
        med = buscar_id(ag, idd)
        if not med:
            return "Nao encontrado."
        med["ativo"] = True
        salvar_agenda_db(ag)
        limpar_sessao()
        return f"<b>Reativado:</b> {med['nome']}<br><br>Digite <b>menu</b> para voltar."
    limpar_sessao()
    return "Erro."


# =============================================
#  DETECCAO
# =============================================

def detectar(msg):
    ml = msg.lower().strip()
    for s in ["oi", "ola", "bom dia", "boa tarde", "boa noite", "hey", "eae"]:
        if ml == s or ml.startswith(s + " ") or ml.startswith(s + ","):
            return "saudacao"
    for a in ["obrigado", "obrigada", "valeu", "brigado", "vlw"]:
        if a in ml:
            return "agradecimento"
    if ml in ["menu", "inicio", "opcoes"]:
        return "menu"
    if ml in ["ajuda", "help", "?", "como funciona"]:
        return "ajuda"
    if ml in ["historico", "h", "historico de doses", "doses tomadas"]:
        return "historico"
    if ml in ["sono", "dormir", "horario de sono", "configurar sono"]:
        return "sono"
    for p in ["adicionar", "cadastrar", "novo", "add", "incluir", "inserir"]:
        if ml == p or ml.startswith(p + " "):
            return "cadastrar"
    for i in ["remedio e", "tomar", "tomo", "preciso tomar", "medico receitou", "devo tomar", "tenho que tomar"]:
        if i in ml:
            return "texto_livre"
    if ml in ["listar", "lista", "ver", "agenda", "remedios", "meus remedios", "mostrar"]:
        return "listar"
    if ml in ["limpar", "apagar tudo", "resetar"]:
        return "limpar"
    if ml in ["status", "resumo"]:
        return "status"
    if ml in ["proximo", "proximo remedio", "qual o proximo"]:
        return "proximo"
    for p in ["remover", "deletar", "excluir"]:
        if ml == p or ml.startswith(p + " "):
            return "remover"
    for p in ["editar", "alterar", "mudar"]:
        if ml == p or ml.startswith(p + " "):
            return "editar"
    for p in ["pausar", "suspender", "desativar"]:
        if ml == p or ml.startswith(p + " "):
            return "pausar"
    for p in ["reativar", "ativar", "retomar"]:
        if ml == p or ml.startswith(p + " "):
            return "reativar"
    for p in ["buscar", "procurar"]:
        if ml.startswith(p + " "):
            return "buscar"
    partes = msg.strip().split()
    if len(partes) >= 3 and normalizar_horario(partes[1]):
        return "cadastro_rapido"
    return "nao_entendido"


# =============================================
#  RESPOSTAS E ATALHOS
# =============================================

def resp_proximo():
    ag = carregar_agenda_db()
    at = sorted([m for m in ag.get("medicamentos", []) if m.get("ativo", True)], key=lambda m: m.get("horario", ""))
    if not at:
        return "Nenhum ativo.<br><br>Digite <b>menu</b> para voltar."
    agora = datetime.now().strftime("%H:%M")
    p = None
    for m in at:
        h = m.get("proxima_dose_ajustada") or m.get("horario", "")
        if h >= agora:
            p = m
            break
    if not p:
        p = at[0]
    h_ex = p.get("proxima_dose_ajustada") or p["horario"]
    aj = " (ajustado)" if p.get("proxima_dose_ajustada") else ""
    obs = f"<br>Obs: {p['observacoes']}" if p.get("observacoes") else ""
    return (
        f"<b>PROXIMO:</b><br><b>{p['nome']}</b> as <b>{h_ex}</b>{aj}<br>"
        f"Dose: {p['dose']}<br>{p.get('categoria', 'normal').upper()}{obs}<br><br>Digite <b>menu</b> para voltar."
    )


def resp_buscar(msg):
    partes = msg.split()
    if len(partes) < 2:
        return "Ex: <b>buscar Losartana</b>"
    nome = " ".join(partes[1:])
    ag = carregar_agenda_db()
    r = buscar_nome(ag, nome)
    if not r:
        r = [m for m in ag.get("medicamentos", []) if nome.lower() in m["nome"].lower()]
    if not r:
        return f"Nenhum com <b>{nome}</b>.<br><br>Digite <b>menu</b> para voltar."
    return fmt_lista(r, f"RESULTADOS: '{nome.upper()}'")


def resp_rapido(msg):
    partes = msg.strip().split()
    nome = partes[0].capitalize()
    h = normalizar_horario(partes[1])
    dose = " ".join(partes[2:])
    if not h:
        return "Horario invalido."
    ag = carregar_agenda_db()
    if tem_dup(ag, nome, h):
        return f"<b>{nome}</b> ja cadastrado as <b>{h}</b>."
    med = {
        "id": prox_id(ag), "nome": nome, "dose": dose,
        "tipo_dose": "", "quantidade_dose": 1, "horario": h, "horario_original": h,
        "intervalo_horas": None, "vezes_por_dia": 1, "modo_uso": "diario",
        "categoria": "normal", "observacoes": "", "ativo": True, "img_arquivo": "",
        "cadastrado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "historico_doses": [], "proxima_dose_ajustada": None,
    }
    ag["medicamentos"].append(med)
    salvar_agenda_db(ag)
    return f"<b>Rapido:</b> ID {med['id']} | {nome} | {h} | {dose}<br><br>Digite <b>menu</b> para voltar."


def atalho(n):
    if n == "1":
        s = obter_sessao()
        s["fluxo"] = "cadastrar"
        s["etapa"] = "nome"
        s["dados_temp"] = {}
        return f"<b>CADASTRAR REMEDIO</b><br><br>{tratar()}, qual o <b>nome do remedio</b>?<br>(<b>cancelar</b> para sair)"
    elif n == "2":
        return fmt_lista(carregar_agenda_db().get("medicamentos", []))
    elif n == "3":
        s = obter_sessao()
        s["fluxo"] = "editar"
        s["etapa"] = "qual"
        s["dados_temp"] = {}
        meds = carregar_agenda_db().get("medicamentos", [])
        if not meds:
            limpar_sessao()
            return "Nenhum remedio.<br><br>" + menu_texto()
        return "<b>EDITAR</b><br>ID ou nome (<b>cancelar</b>):<br><br>" + fmt_lista(meds)
    elif n == "4":
        s = obter_sessao()
        s["fluxo"] = "remover"
        s["etapa"] = "qual"
        s["dados_temp"] = {}
        meds = carregar_agenda_db().get("medicamentos", [])
        if not meds:
            limpar_sessao()
            return "Nada para remover.<br><br>" + menu_texto()
        return "<b>REMOVER</b><br>ID ou nome (<b>cancelar</b>):<br><br>" + fmt_lista(meds)
    elif n == "5":
        return resp_proximo()
    elif n == "6":
        s = obter_sessao()
        s["fluxo"] = "pr"
        s["etapa"] = "escolha"
        s["dados_temp"] = {}
        return "<b>PAUSAR / REATIVAR</b><br><br><b>1.</b> Pausar<br><b>2.</b> Reativar<br><br><b>cancelar</b>"
    elif n == "7":
        s = obter_sessao()
        s["fluxo"] = "sono"
        s["etapa"] = "inicio"
        s["dados_temp"] = {}
        c = carregar_agenda_db().get("configuracoes", {})
        return f"<b>SONO</b><br>Atual: {c.get('horario_sono_inicio', '23:00')}-{c.get('horario_sono_fim', '07:00')}<br><br>Que horas <b>dorme</b>? (<b>cancelar</b>)"
    elif n == "8":
        s = obter_sessao()
        s["fluxo"] = "cadastrar"
        s["etapa"] = "texto_livre"
        s["dados_temp"] = {}
        return "<b>CADASTRO POR DESCRICAO</b><br><br>Ex: 'Preciso tomar Dipirona 500mg, 2 comprimidos a cada 8h, as 10h'<br><br>Escreva: (<b>cancelar</b>)"
    elif n == "9":
        s = obter_sessao()
        s["fluxo"] = "buscar"
        s["etapa"] = "nome"
        s["dados_temp"] = {}
        return "<b>BUSCAR</b><br>Nome do remedio: (<b>cancelar</b>)"
    elif n == "0":
        return (
            "<b>AJUDA PINAID</b><br><br>"
            "<b>Cadastro guiado:</b> opcao 1<br>"
            "<b>Cadastro por descricao:</b> opcao 8<br>"
            "<b>Cadastro rapido:</b> Losartana 08:00 50mg<br><br>"
            "<b>Tipos de uso:</b><br>"
            "- Diario: X doses por dia (distribuidas antes do sono)<br>"
            "- Intervalo fixo: a cada Xh por Y doses (pode ultrapassar 1 dia)<br><br>"
            "<b>Categorias:</b><br>"
            "- Essencial: alarma SEMPRE<br>"
            "- Normal: nao alarma durante sono<br><br>"
            "<b>Ajuste automatico:</b> se atrasar, proxima dose e recalculada<br>"
            "<b>Historico:</b> <b>h</b> ou <b>historico</b><br><br>"
            "Digite <b>menu</b> para voltar."
        )
    return None


# =============================================
#  PROCESSAMENTO PRINCIPAL
# =============================================

def processar(msg):
    ml = msg.strip()
    sessao = obter_sessao()

    # Fluxo nome paciente
    if sessao["fluxo"] == "paciente":
        return fluxo_paciente(ml, sessao)

    # Se nao tem nome, inicia fluxo
    if not nome_paciente() and sessao["fluxo"] is None:
        s = obter_sessao()
        s["fluxo"] = "paciente"
        s["etapa"] = "nome"
        # A primeira mensagem E o nome
        return fluxo_paciente(ml, s)

    # Fluxos ativos
    if sessao["fluxo"] == "cadastrar":
        return fluxo_cadastrar(ml, sessao)
    elif sessao["fluxo"] == "editar":
        return fluxo_editar(ml, sessao)
    elif sessao["fluxo"] == "remover":
        return fluxo_remover(ml, sessao)
    elif sessao["fluxo"] == "sono":
        return fluxo_sono(ml, sessao)
    elif sessao["fluxo"] == "pr":
        return fluxo_pr(ml, sessao)
    elif sessao["fluxo"] == "buscar":
        if ml.lower() in ["cancelar", "sair", "voltar", "menu"]:
            limpar_sessao()
            return "Cancelado.<br><br>" + menu_texto()
        limpar_sessao()
        return resp_buscar("buscar " + ml)

    # Atalhos
    if ml in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        r = atalho(ml)
        if r:
            return r
    if ml.lower() in ["h", "historico"]:
        return formatar_historico()

    intent = detectar(ml)
    if intent == "saudacao":
        return menu_texto()
    elif intent == "agradecimento":
        return f"De nada, {tratar()}! <b>menu</b> para voltar."
    elif intent == "menu":
        return menu_texto()
    elif intent == "ajuda":
        return atalho("0")
    elif intent == "historico":
        return formatar_historico()
    elif intent == "sono":
        return atalho("7")
    elif intent == "cadastrar":
        return atalho("1")
    elif intent == "texto_livre":
        s = obter_sessao()
        s["fluxo"] = "cadastrar"
        s["etapa"] = "texto_livre"
        s["dados_temp"] = {}
        return fluxo_cadastrar(ml, s)
    elif intent == "listar":
        return atalho("2")
    elif intent == "limpar":
        ag = carregar_agenda_db()
        qtd = len(ag.get("medicamentos", []))
        if qtd == 0:
            return "Ja vazia.<br><br>" + menu_texto()
        ag["medicamentos"] = []
        salvar_agenda_db(ag)
        return f"<b>{qtd}</b> removido(s).<br><br>" + menu_texto()
    elif intent == "status":
        ag = carregar_agenda_db()
        meds = ag.get("medicamentos", [])
        total = len(meds)
        ativos = len([m for m in meds if m.get("ativo", True)])
        c = ag.get("configuracoes", {})
        return (
            f"<b>STATUS</b><br>Paciente: {tratar()}<br>"
            f"Total: {total} | Ativos: {ativos} | Pausados: {total - ativos}<br>"
            f"Sono: {c.get('horario_sono_inicio', '23:00')}-{c.get('horario_sono_fim', '07:00')}<br>"
            f"Agora: {datetime.now().strftime('%H:%M')}<br><br><b>menu</b> para voltar."
        )
    elif intent == "proximo":
        return resp_proximo()
    elif intent == "remover":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao()
            s["fluxo"] = "remover"
            s["etapa"] = "qual"
            s["dados_temp"] = {}
            return fluxo_remover(" ".join(partes[1:]), s)
        return atalho("4")
    elif intent == "editar":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao()
            s["fluxo"] = "editar"
            s["etapa"] = "qual"
            s["dados_temp"] = {}
            return fluxo_editar(partes[1], s)
        return atalho("3")
    elif intent == "pausar":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao()
            s["fluxo"] = "pr"
            s["etapa"] = "pausar"
            s["dados_temp"] = {}
            return fluxo_pr(partes[1], s)
        return atalho("6")
    elif intent == "reativar":
        partes = ml.split()
        if len(partes) >= 2:
            s = obter_sessao()
            s["fluxo"] = "pr"
            s["etapa"] = "reativar"
            s["dados_temp"] = {}
            return fluxo_pr(partes[1], s)
        return atalho("6")
    elif intent == "buscar":
        return resp_buscar(ml)
    elif intent == "cadastro_rapido":
        return resp_rapido(ml)
    else:
        return f"Nao entendi: <b>{ml}</b><br><br>Digite <b>menu</b> para opcoes."


# =============================================
#  ROTAS
# =============================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat_bot():
    d = request.json
    if not d or "message" not in d:
        return jsonify({"reply": "Vazia."}), 400
    return jsonify({"reply": processar(d["message"])})


@app.route("/api/agenda")
def api_agenda():
    ag = carregar_agenda_db()
    meds = []
    for m in ag.get("medicamentos", []):
        if not m.get("ativo", True):
            continue
        me = dict(m)
        if m.get("proxima_dose_ajustada"):
            me["horario"] = m["proxima_dose_ajustada"]
        meds.append(me)
    return jsonify({
        "configuracoes": ag.get("configuracoes", {}),
        "paciente": ag.get("paciente", {}),
        "medicamentos": meds,
    })


@app.route("/api/imagens/<path:f>")
def api_img(f):
    c = os.path.join(PASTA_IMAGENS, f)
    return send_from_directory(PASTA_IMAGENS, f) if os.path.exists(c) else (jsonify({"erro": "404"}), 404)


@app.route("/api/confirmar", methods=["POST"])
def api_confirmar():
    d = request.json
    if not d:
        return jsonify({"status": "erro"}), 400
    med_nome = d.get("medicamento", "?")
    h_prog = d.get("horario", "--:--")
    h_real = d.get("horario_real", "--:--")
    ag = carregar_agenda_db()
    prox_aj = None
    for med in ag.get("medicamentos", []):
        if med["nome"] == med_nome and med["horario"] == h_prog:
            if "historico_doses" not in med:
                med["historico_doses"] = []
            reg = {"programado": h_prog, "real": h_real,
                   "data": datetime.now().strftime("%d/%m/%Y"), "proxima_ajustada": None}
            nova = recalcular_proxima_dose(med, h_real)
            if nova:
                prox_meds = [m for m in ag.get("medicamentos", [])
                             if m["nome"] == med_nome and m["horario"] > h_prog and m.get("ativo", True)]
                prox_meds.sort(key=lambda m: m["horario"])
                if prox_meds:
                    p = prox_meds[0]
                    pp = h_prog.split(":")
                    rp = h_real.split(":")
                    atraso = (int(rp[0]) * 60 + int(rp[1])) - (int(pp[0]) * 60 + int(pp[1]))
                    if atraso > 0:
                        ho = hm(p.get("horario_original", p["horario"]))
                        nn = ho + atraso
                        if nn < 1440:
                            nh = mh(nn)
                            p["proxima_dose_ajustada"] = nh
                            reg["proxima_ajustada"] = nh
                            prox_aj = nh
            med["proxima_dose_ajustada"] = None
            med["historico_doses"].append(reg)
            salvar_agenda_db(ag)
            break
    resp = {"status": "ok"}
    if prox_aj:
        resp["proxima_dose_ajustada"] = prox_aj
    return jsonify(resp)


if __name__ == "__main__":
    print("=" * 40)
    print("  PINAID | http://127.0.0.1:5000")
    print("=" * 40)
    app.run(host="0.0.0.0", port=5000, debug=True)