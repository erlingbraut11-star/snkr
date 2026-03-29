import os
import json
import logging
import anthropic
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# ============================================================
# CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# PROMPT SCOUT SNEAKERS
# ============================================================

SNEAKER_PROMPT = """Tu es un expert sneakers et resell. 
Quand on te donne le nom ou la référence SKU d'une sneaker, tu utilises web_search pour trouver :

1. Le prix moyen sur StockX (cherche sur stockx.com)
2. Le prix moyen sur Vinted (cherche sur vinted.fr)

Réponds UNIQUEMENT avec ce JSON, sans texte avant ou après :
{
  "nom": "Nom complet de la sneaker",
  "sku": "SKU si trouvé, sinon null",
  "image_url": "URL image si trouvée, sinon null",
  "stockx": {
    "prix_moyen": "ex: 180€",
    "fourchette": "ex: 150€ - 220€",
    "derniere_vente": "ex: 175€",
    "lien": "URL directe vers la sneaker sur StockX"
  },
  "vinted": {
    "prix_moyen": "ex: 120€",
    "fourchette": "ex: 90€ - 150€",
    "annonces_trouvees": "ex: 12 annonces",
    "lien": "URL de recherche sur Vinted"
  },
  "analyse": "2 phrases : est-ce une bonne affaire sur Vinted vs StockX ? Vaut-il mieux acheter ou revendre ?",
  "verdict": "ACHETER sur Vinted 🟢 / REVENDRE sur StockX 🔴 / ATTENDRE 🟡"
}

Si tu ne trouves pas la sneaker, retourne :
{
  "erreur": "Sneaker non trouvée. Essaie avec un nom plus précis ou le SKU."
}"""


async def search_sneaker_prices(query: str) -> str:
    """Recherche les prix d'une sneaker via Claude + web_search"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info(f"🔍 Recherche prix pour : {query}")

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SNEAKER_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": f"Trouve les prix de cette sneaker : {query}"}]
        )

        full_text = "".join(b.text for b in response.content if hasattr(b, "text"))

        # Extraction robuste du JSON même si Claude ajoute du texte autour
        clean = full_text.strip()
        clean = clean.replace("```json", "").replace("```", "").strip()

        # Cherche le premier { et le dernier } pour extraire uniquement le JSON
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            logger.error(f"Pas de JSON trouvé dans la réponse : {clean[:300]}")
            return "❌ Sneaker non trouvée. Essaie avec un nom plus précis."

        clean = clean[start:end]
        data = json.loads(clean)

        if "erreur" in data:
            return f"❌ {data['erreur']}"

        return format_sneaker_result(data)

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON invalide : {e} — Réponse : {full_text[:300]}")
        return "❌ Résultat illisible. Réessaie avec un nom plus précis ex: `Nike Dunk Low Panda`"
    except Exception as e:
        logger.error(f"❌ Erreur recherche sneaker: {e}")
        return "❌ Une erreur est survenue. Réessaie dans quelques secondes."


def format_sneaker_result(data: dict) -> str:
    """Formate le résultat en message Telegram lisible"""

    verdict = data.get("verdict", "")
    stockx = data.get("stockx", {})
    vinted = data.get("vinted", {})

    msg = f"👟 *{data.get('nom', 'Sneaker')}*"

    if data.get("sku"):
        msg += f"\n🏷️ SKU : `{data['sku']}`"

    msg += "\n\n"

    # StockX
    msg += "📦 *StockX*\n"
    msg += f"  💰 Prix moyen : *{stockx.get('prix_moyen', 'N/A')}*\n"
    msg += f"  📊 Fourchette : {stockx.get('fourchette', 'N/A')}\n"
    msg += f"  🕐 Dernière vente : {stockx.get('derniere_vente', 'N/A')}\n"
    if stockx.get("lien"):
        msg += f"  🔗 [Voir sur StockX]({stockx['lien']})\n"

    msg += "\n"

    # Vinted
    msg += "🛍️ *Vinted*\n"
    msg += f"  💰 Prix moyen : *{vinted.get('prix_moyen', 'N/A')}*\n"
    msg += f"  📊 Fourchette : {vinted.get('fourchette', 'N/A')}\n"
    msg += f"  📋 Annonces : {vinted.get('annonces_trouvees', 'N/A')}\n"
    if vinted.get("lien"):
        msg += f"  🔗 [Voir sur Vinted]({vinted['lien']})\n"

    msg += "\n"

    # Analyse
    msg += f"📊 *Analyse :*\n{data.get('analyse', '')}\n\n"

    # Verdict
    msg += f"🎯 *Verdict :* {verdict}"

    return msg


# ============================================================
# COMMANDES TELEGRAM
# ============================================================

async def start_command(update, context):
    await update.message.reply_text(
        "👟 *SneakerBot — Scanner de prix*\n\n"
        "Je compare les prix sur *StockX* et *Vinted* pour n'importe quelle sneaker.\n\n"
        "📋 *Comment utiliser :*\n"
        "• Tape directement le nom de la sneaker\n"
        "• Ou envoie le SKU (ex: `555088-134`)\n\n"
        "📌 *Exemples :*\n"
        "`Air Jordan 1 Retro High OG Bred`\n"
        "`Nike Dunk Low Panda`\n"
        "`Yeezy Boost 350 V2 Zebra`\n"
        "`555088-134`\n\n"
        "/help — Aide\n\n"
        "Lance une recherche ! 🚀",
        parse_mode="Markdown"
    )


async def help_command(update, context):
    await update.message.reply_text(
        "📖 *Aide SneakerBot*\n\n"
        "Tape le nom ou le SKU d'une sneaker et je te donne :\n\n"
        "• 💰 Le prix moyen sur *StockX*\n"
        "• 🛍️ Le prix moyen sur *Vinted*\n"
        "• 📊 La fourchette de prix\n"
        "• 🎯 Un verdict : acheter ou revendre ?\n\n"
        "⏱️ La recherche prend environ 15-20 secondes.",
        parse_mode="Markdown"
    )


async def message_handler(update, context):
    query = update.message.text.strip()

    if len(query) < 3:
        await update.message.reply_text("❌ Tape un nom de sneaker plus précis !")
        return

    await update.message.reply_text(
        f"🔍 *Recherche en cours...*\n`{query}`\n\n_Patiente 15-20 secondes !_",
        parse_mode="Markdown"
    )

    result = await search_sneaker_prices(query)

    await update.message.reply_text(
        result,
        parse_mode="Markdown",
        disable_web_page_preview=False
    )


# ============================================================
# MAIN
# ============================================================

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("❌ TELEGRAM_TOKEN manquant !")
    if not ANTHROPIC_API_KEY:
        raise ValueError("❌ ANTHROPIC_API_KEY manquant !")

    logger.info("🚀 Démarrage SneakerBot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("✅ SneakerBot est en ligne !")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
