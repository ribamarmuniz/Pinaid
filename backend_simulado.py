import json
import os
from PIL import Image, ImageOps, ImageDraw, ImageFont

# --- CONFIGURACOES ---
PASTA_ORIGEM = "fotos_originais"
PASTA_DESTINO = "imagens_pulseira"
ARQUIVO_AGENDA = "agenda.json"

TELA_LARGURA = 128
TELA_ALTURA = 160

if not os.path.exists(PASTA_ORIGEM):
    os.makedirs(PASTA_ORIGEM)
    print(f"[i] Pasta '{PASTA_ORIGEM}' criada.")

if not os.path.exists(PASTA_DESTINO):
    os.makedirs(PASTA_DESTINO)


def processar_imagem(nome_arquivo_origem, nome_final):
    """
    Redimensiona para 128x160 ocupando TUDO.
    Sem bordas, sem overlay. Foto pura fullscreen.
    """
    caminho_origem = os.path.join(PASTA_ORIGEM, nome_arquivo_origem)
    caminho_final = os.path.join(PASTA_DESTINO, nome_final)

    try:
        img = Image.open(caminho_origem)

        # Fundo preto
        fundo = Image.new('RGB', (TELA_LARGURA, TELA_ALTURA), (0, 0, 0))

        # Redimensiona mantendo proporcao
        img_redimensionada = ImageOps.contain(
            img,
            (TELA_LARGURA, TELA_ALTURA),
            method=Image.Resampling.LANCZOS
        )

        # Centraliza
        pos_x = (TELA_LARGURA - img_redimensionada.width) // 2
        pos_y = (TELA_ALTURA - img_redimensionada.height) // 2
        fundo.paste(img_redimensionada, (pos_x, pos_y))

        fundo.save(caminho_final, "JPEG", quality=95)
        print(f"  [OK] {nome_arquivo_origem} -> {caminho_final}")
        return True

    except FileNotFoundError:
        print(f"  [X] Nao encontrado: {caminho_origem}")
        return False
    except Exception as e:
        print(f"  [X] Erro: {e}")
        return False


def gerar_placeholder(nome_final):
    """Placeholder elegante quando nao tem foto."""
    caminho_final = os.path.join(PASTA_DESTINO, nome_final)
    img = Image.new('RGB', (TELA_LARGURA, TELA_ALTURA), (13, 17, 23))
    draw = ImageDraw.Draw(img)

    # Moldura central
    draw.rounded_rectangle(
        [(24, 45), (104, 105)],
        radius=8,
        outline=(55, 55, 65),
        width=2
    )

    # X
    cx, cy = TELA_LARGURA // 2, 75
    draw.line([(cx - 15, cy - 15), (cx + 15, cy + 15)], fill=(70, 78, 90), width=2)
    draw.line([(cx + 15, cy - 15), (cx - 15, cy + 15)], fill=(70, 78, 90), width=2)

    try:
        fonte = ImageFont.truetype("arial.ttf", 11)
    except:
        fonte = ImageFont.load_default()

    texto = "SEM FOTO"
    bbox = draw.textbbox((0, 0), texto, font=fonte)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((TELA_LARGURA - tw) // 2, 115),
        texto, fill=(140, 148, 160), font=fonte
    )

    img.save(caminho_final, "JPEG", quality=95)
    print(f"  [OK] Placeholder: {caminho_final}")


def gerar_agenda_atualizada():
    agenda = {
        "usuario": "Dona Maria",
        "versao": "2.0",
        "medicamentos": [
            {
                "id": 1,
                "nome": "Losartana",
                "dose": "50mg",
                "instrucao": "Tomar 1 cp",
                "horario": "08:00",
                "img_arquivo": "remedio_1.jpg"
            }
        ]
    }
    with open(ARQUIVO_AGENDA, 'w', encoding='utf-8') as f:
        json.dump(agenda, f, indent=4, ensure_ascii=False)
    print(f"  [OK] {ARQUIVO_AGENDA} salvo.")


if __name__ == "__main__":
    print("=" * 42)
    print("  PULSEIRA INTELIGENTE - Setup de Imagens")
    print("=" * 42)
    print()

    print("[1] Gerando agenda...")
    gerar_agenda_atualizada()
    print()

    print("[2] Processando imagens...")
    foto = os.path.join(PASTA_ORIGEM, "foto1.jpg")
    if os.path.exists(foto):
        processar_imagem("foto1.jpg", "remedio_1.jpg")
    else:
        print(f"  [!] 'foto1.jpg' nao encontrada em '{PASTA_ORIGEM}'")
        gerar_placeholder("remedio_1.jpg")
    print()

    print("[3] Pronto!")
    print(f"  -> Execute: python mock_pulseira.py")
    print("=" * 42)