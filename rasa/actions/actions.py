import requests
import random
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

SERVIDOR_URL = "http://127.0.0.1:5000"


# Respostas conversacionais que o Rasa da diretamente (comportamento de IA)
RESPOSTAS_CONVERSA = {
    "conversa_geral": [
        "Estou bem, obrigado por perguntar! Sou o Pinaid, seu assistente de medicamentos. Como posso ajudar?",
        "Tudo otimo por aqui! Estou pronto para ajudar com seus remedios. Digite <b>menu</b> para ver as opcoes.",
        "Fico feliz que esteja aqui! Posso ajudar a gerenciar seus medicamentos. O que precisa?",
        "Estou funcionando perfeitamente! Precisa cadastrar ou verificar algum remedio?",
    ],
    "pergunta_saude": [
        "Essa e uma otima pergunta, mas sou um assistente de gerenciamento de medicamentos, nao um medico. "
        "Recomendo consultar seu medico ou farmaceutico para duvidas sobre interacoes e efeitos colaterais.<br><br>"
        "Posso ajudar a organizar seus horarios de remedios! Digite <b>menu</b> para ver as opcoes.",
        "Importante: nao sou um profissional de saude. Para duvidas sobre medicamentos, procure seu medico.<br><br>"
        "Minha funcao e ajudar voce a lembrar de tomar os remedios no horario certo! Digite <b>menu</b>.",
        "Nao tenho qualificacao para dar conselhos medicos. Consulte seu medico ou farmaceutico!<br><br>"
        "Posso ajudar organizando seus horarios. Quer cadastrar um remedio? Digite <b>1</b>.",
    ],
    "despedida": [
        "Ate mais! Lembre-se de tomar seus remedios nos horarios certos. Cuide-se!",
        "Tchau! Estarei aqui quando precisar. Nao esqueca dos seus medicamentos!",
        "Ate logo! Qualquer duvida sobre seus remedios, e so voltar. Saude!",
        "Bye! Cuide-se bem e nao pule nenhuma dose!",
    ],
    "elogio": [
        "Obrigado! Fico feliz em ajudar. Se precisar de algo mais, e so falar!<br><br>Digite <b>menu</b> para ver as opcoes.",
        "Que bom que gostou! Estou aqui para facilitar o controle dos seus medicamentos.<br><br>Digite <b>menu</b>.",
        "Valeu! Meu objetivo e garantir que nenhuma dose seja esquecida. Como posso ajudar mais?",
    ],
    "reclamacao": [
        "Sinto muito que nao tenha ficado satisfeito. Pode me dizer o que aconteceu? Vou tentar melhorar!<br><br>"
        "Se quiser recomecar, digite <b>menu</b>.",
        "Desculpe pelo inconveniente. Estou sempre aprendendo! Tente digitar <b>ajuda</b> para ver como posso ajudar melhor.",
        "Lamento! Se algo deu errado, tente <b>cancelar</b> e recomecar. Estou aqui para ajudar!",
    ],
    "quem_e_voce": [
        "<b>Sou o Pinaid!</b><br><br>"
        "Sou um assistente inteligente de gerenciamento de medicamentos. Fui criado para ajudar cuidadores "
        "e pacientes a nunca esquecerem de tomar seus remedios.<br><br>"
        "<b>O que faco:</b><br>"
        "- Cadastro e organizo medicamentos<br>"
        "- Calculo horarios automaticamente<br>"
        "- Envio alarmes na pulseira do paciente<br>"
        "- Registro historico de doses tomadas<br>"
        "- Respeito horarios de sono<br><br>"
        "Digite <b>menu</b> para comecar!",
    ],
}


def resposta_conversacional(intent):
    """Retorna resposta direta do Rasa para intents conversacionais."""
    if intent in RESPOSTAS_CONVERSA:
        return random.choice(RESPOSTAS_CONVERSA[intent])
    return None


class ActionProcessarMensagem(Action):

    def name(self) -> Text:
        return "action_processar_mensagem"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        mensagem_original = tracker.latest_message.get("text", "")
        intent = tracker.latest_message.get("intent", {}).get("name", "")
        confidence = tracker.latest_message.get("intent", {}).get("confidence", 0)
        entities = tracker.latest_message.get("entities", [])

        # Log para debug
        print(f"[RASA] Intent: {intent} ({confidence:.2f}) | Msg: {mensagem_original}")
        if entities:
            print(f"[RASA] Entities: {entities}")

        # 1. Verifica se e um intent conversacional que o Rasa responde direto
        resp_conv = resposta_conversacional(intent)
        if resp_conv:
            dispatcher.utter_message(text=resp_conv)
            return []

        # 2. Para todos os outros intents, repassa ao servidor Flask
        mensagem_para_servidor = self._montar_mensagem(
            mensagem_original, intent, entities, confidence
        )

        try:
            resp = requests.post(
                f"{SERVIDOR_URL}/chat",
                json={"message": mensagem_para_servidor},
                timeout=10
            )

            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("reply", "Erro ao processar.")
                dispatcher.utter_message(text=reply)
            else:
                dispatcher.utter_message(
                    text="Erro ao comunicar com o servidor."
                )

        except requests.exceptions.ConnectionError:
            dispatcher.utter_message(
                text="Servidor Pinaid offline. Verifique se esta rodando na porta 5000."
            )
        except requests.exceptions.Timeout:
            dispatcher.utter_message(
                text="Servidor demorou para responder. Tente novamente."
            )
        except Exception as ex:
            dispatcher.utter_message(
                text=f"Erro inesperado: {str(ex)}"
            )

        return []

    def _montar_mensagem(self, original: str, intent: str, entities: list, confidence: float) -> str:
        """
        Decide qual mensagem enviar ao servidor Flask.
        """

        # Mapeamento de intents para comandos simples
        mapa_simples = {
            "saudacao": "oi",
            "menu": "menu",
            "ajuda": "ajuda",
            "listar": "listar",
            "proximo": "proximo",
            "historico": "historico",
            "status": "status",
            "limpar": "limpar",
            "configurar_sono": "sono",
            "pausar_reativar": "6",
            "agradecimento": "obrigado",
        }

        if intent in mapa_simples:
            return mapa_simples[intent]

        # Confirmar / negar / cancelar / pular
        mapa_resp = {
            "confirmar_sim": "sim",
            "confirmar_nao": "nao",
            "cancelar": "cancelar",
            "pular": "nao",
        }
        if intent in mapa_resp:
            return mapa_resp[intent]

        # Cadastrar sem entidades = atalho
        if intent == "cadastrar" and not entities:
            return "1"

        # Cadastro por descricao
        if intent == "cadastro_descricao":
            if original.strip() == "8":
                return "8"
            return original

        # Cadastro rapido: Nome HH:MM dose
        if intent == "cadastro_rapido":
            nome = ""
            horario = ""
            dose = ""
            for ent in entities:
                if ent["entity"] == "nome_remedio":
                    nome = ent["value"]
                elif ent["entity"] == "horario":
                    horario = ent["value"]
                elif ent["entity"] == "dose":
                    dose = ent["value"]
            if nome and horario and dose:
                return f"{nome} {horario} {dose}"
            return original

        # Editar com ID ou nome
        if intent == "editar":
            for ent in entities:
                if ent["entity"] == "id_remedio":
                    return f"editar {ent['value']}"
                if ent["entity"] == "nome_remedio":
                    return f"editar {ent['value']}"
            if original.strip() == "3":
                return "3"
            return "editar"

        # Remover com ID ou nome
        if intent == "remover":
            for ent in entities:
                if ent["entity"] == "id_remedio":
                    return f"remover {ent['value']}"
                if ent["entity"] == "nome_remedio":
                    return f"remover {ent['value']}"
            if original.strip() == "4":
                return "4"
            return "remover"

        # Pausar com ID ou nome
        if intent == "pausar":
            for ent in entities:
                if ent["entity"] == "id_remedio":
                    return f"pausar {ent['value']}"
                if ent["entity"] == "nome_remedio":
                    return f"pausar {ent['value']}"
            return "pausar"

        # Reativar
        if intent == "reativar":
            for ent in entities:
                if ent["entity"] == "id_remedio":
                    return f"reativar {ent['value']}"
                if ent["entity"] == "nome_remedio":
                    return f"reativar {ent['value']}"
            return "reativar"

        # Buscar
        if intent == "buscar":
            for ent in entities:
                if ent["entity"] == "nome_remedio":
                    return f"buscar {ent['value']}"
            if original.strip() == "9":
                return "9"
            return "buscar"

        # Informar horario
        if intent == "informar_horario":
            for ent in entities:
                if ent["entity"] == "horario":
                    return ent["value"]
            return original

        # Informar dose
        if intent == "informar_dose":
            for ent in entities:
                if ent["entity"] == "dose":
                    return ent["value"]
            return original

        # Informar numero
        if intent == "informar_numero":
            for ent in entities:
                if ent["entity"] == "numero":
                    return ent["value"]
            return original

        # Informar nome
        if intent == "informar_nome":
            for ent in entities:
                if ent["entity"] == "nome_pessoa":
                    return ent["value"]
            return original

        # Informar categoria
        if intent == "informar_categoria":
            texto_lower = original.lower().strip()
            if "essencial" in texto_lower:
                return "1"
            elif "normal" in texto_lower:
                return "2"
            return original

        # Informar tipo dose
        if intent == "informar_tipo_dose":
            texto_lower = original.lower().strip()
            mapa_tipo = {
                "comprimido": "1", "capsula": "2", "gotas": "3",
                "liquido": "4", "injecao": "5", "outro": "6"
            }
            for chave, valor in mapa_tipo.items():
                if chave in texto_lower:
                    return valor
            return original

        # Informar modo dose
        if intent == "informar_modo_dose":
            texto_lower = original.lower().strip()
            if "dia" in texto_lower or "distribuir" in texto_lower:
                return "1"
            elif "intervalo" in texto_lower or "cada" in texto_lower:
                return "2"
            return original

        # Fallback: envia texto original
        return original