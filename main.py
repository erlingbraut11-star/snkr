import asyncio
import logging
import json
import re
from datetime import datetime
import anthropic
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ============================================================
# CONFIGURATION
# ============================================================
TELEGRAM_TOKEN = "METS_TON_TOKEN_ICI"
ANTHROPIC_API_KEY = "METS_TA_CLE_ANTHROPIC_ICI"
CHAT_ID = None
MARGE_MINIMUM = 20  # €

# ============================================================
# SYSTEM PROMPT
# ============================================================
SYSTEM_PROMPT = """Tu es SNKR, un expert en achat-revente de sneakers.

ÉTAPE 1 — Utilise web_search pour chercher sur Vinted les sneakers récemment mises en vente de ces marques : Nike, Jordan, New Balance.
Recherche des annonces récentes avec des prix potentiellement sous-évalués.

ÉTAPE 2 — Pour chaque sneaker trouvée sur Vinted, utilise web_search pour trouver son prix actuel sur StockX (prix de revente du marché).

ÉTAPE 3 — Calcule la marge NETTE réelle en tenant compte de TOUS les frais :

FRAIS ACHAT VINTED :
- Frais service acheteur : 5% du prix + 0.70€
- Frais de port estimé : 6€

FRAIS REVENTE STOCKX :
- Commission vendeur : 9.5% du prix de vente
- Frais de traitement : 3% du prix de vente
- Frais de port : 13€

CALCUL :
- Coût total achat = prix_vinted + (prix_vinted × 5% + 0.70€) + 6€
- Revenu net revente = prix_stockx - (prix_stockx × 12.5%) - 13€
- Marge nette = Revenu net revente - Coût total achat

Ne retourne QUE les sneakers avec une marge NETTE >= 20€.

Réponds UNIQUEMENT avec ce JSON :
[
  {
    "sneaker": "Nom exact du modèle",
    "marque": "Nike" | "Jordan" | "New Balance",
    "taille": "ex: 42 ou US9",
    "etat": "Neuf" | "Très bon état" | "Bon état",
    "prix_vinted": 95,
    "frais_achat": 11,
    "cout_total_achat": 106,
    "prix_stockx": 200,
    "frais_revente": 38,
    "revenu_net_revente": 162,
    "marge_nette": 56,
    "lien_vinted": "URL de l'annonce si disponible",
    "analyse": "Pourquoi c'est une bonne affaire en 1-2 phrases",
    "risque": "Faible" | "Moyen" | "Élevé",
    "verdict": "ACHÈTE" | "PASSE"
  }
]

Si aucune bonne affaire trouvée, retourne : []
JSON uniquement, aucun texte avant ou après."""

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# ANALYSE SNKR
# ============================================================
async def run_snkr_analysis():
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("🔍 SNKR lance la recherche de bonnes affaires...")

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": f"Trouve les meilleures affaires sneakers Nike, Jordan, New Balance sur Vinted avec une marge minimum de {MARGE_MINIMUM}€ par rapport à StockX."}]
        )

        full_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                full_text += block.text

        clean = full_text.replace("```json", "").replace("```", "").strip()
        deals = json.loads(clean)
        filtered = [d for d in deals if d.get("marge_nette", 0) >= MARGE_MINIMUM and d.get("verdict") == "ACHÈTE"]
        logger.info(f"✅ {len(filtered)} bonne(s) affaire(s) trouvée(s)")
        return filtered

    except Exception as e:
        logger.error(f"❌ Erreur analyse SNKR: {e}")
        return []

# ============================================================
# FORMATAGE MESSAGE
# ============================================================
def format_deal(d):
    risque_emoji = {"Faible": "🟢", "Moyen": "🟡", "Élevé": "🔴"}.get(d.get("risque", "Moyen"), "🟡")
    marque_emoji = {"Nike": "✔️", "Jordan": "🏀", "New Balance": "🔵"}.get(d.get("marque", ""), "👟")
    marge = d.get("marge_nette", 0)
    stars = "🔥🔥" if marge >= 100 else "🔥" if marge >= 50 else "⭐"

    msg = f"{stars} *{d.get('sneaker', '')}*\n"
    msg += f"{marque_emoji} {d.get('marque', '')} · Taille {d.get('taille', '?')} · {d.get('etat', '?')}\n\n"
    
    msg += f"🛒 *Achat Vinted :*\n"
    msg += f"  Prix annonce : {d.get('prix_vinted', '?')}€\n"
    msg += f"  Frais Vinted + port : {d.get('frais_achat', '?')}€\n"
    msg += f"  💸 Coût total : *{d.get('cout_total_achat', '?')}€*\n\n"
    
    msg += f"📈 *Revente StockX :*\n"
    msg += f"  Prix marché : {d.get('prix_stockx', '?')}€\n"
    msg += f"  Commissions + port : {d.get('frais_revente', '?')}€\n"
    msg += f"  💰 Revenu net : *{d.get('revenu_net_revente', '?')}€*\n\n"
    
    msg += f"✅ *Marge nette réelle : {marge}€*\n\n"
    msg += f"📊 {d.get('analyse', '')}\n\n"
    msg += f"{risque_emoji} *Risque :* {d.get('risque', '?')}\n"

    if d.get("lien_vinted") and d["lien_vinted"] != "URL de l'annonce si disponible":
        msg += f"🔗 [Voir l'annonce Vinted]({d['lien_vinted']})\n"

    msg += f"\n🎯 _{d.get('verdict', '')}_"
    return msg

def format_daily_message(deals):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    if not deals:
        return (
            "👟 *SNKR — Scan du jour*\n"
            f"📅 {now}\n\n"
            f"Aucune bonne affaire avec {MARGE_MINIMUM}€+ de marge trouvée pour l'instant.\n"
            "SNKR continue de surveiller ! 👀"
        )

    total_marge = sum(d.get("marge_nette", 0) for d in deals)
    header = (
        f"👟 *SNKR — Bonnes affaires du {now}*\n"
        f"🔥 *{len(deals)} affaire(s) détectée(s) · {MARGE_MINIMUM}€+ de marge*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    body = "\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n".join(format_deal(d) for d in deals)

    footer = (
        f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Marge totale potentielle : {total_marge}€*\n"
        "⚠️ _Vérifie toujours l'annonce avant d'acheter._"
    )

    return header + body + footer

# ============================================================
# ENVOI TELEGRAM
# ============================================================
async def send_deals(bot=None, chat_id=None):
    target_chat = chat_id or CHAT_ID
    if not target_chat or not bot:
        logger.warning("⚠️ Chat ID non défini. Envoie /start au bot d'abord.")
        return

    try:
        await bot.send_message(
            chat_id=target_chat,
            text="🔍 *SNKR scanne Vinted & StockX...*\n_Recherche des meilleures affaires — patiente 30 secondes !_",
            parse_mode="Markdown"
        )

        deals = await run_snkr_analysis()
        message = format_daily_message(deals)

        if len(message) > 4000:
            chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for chunk in chunks:
                await bot.send_message(chat_id=target_chat, text=chunk, parse_mode="Markdown")
        else:
            await bot.send_message(chat_id=target_chat, text=message, parse_mode="Markdown")

        logger.info(f"✅ Deals envoyés à {target_chat}")

    except Exception as e:
        logger.error(f"❌ Erreur envoi: {e}")
        if bot and target_chat:
            await bot.send_message(chat_id=target_chat, text=f"❌ Erreur SNKR: {str(e)}")

# ============================================================
# COMMANDES TELEGRAM
# ============================================================
async def start_command(update, context):
    global CHAT_ID
    CHAT_ID = str(update.effective_chat.id)

    await update.message.reply_text(
        "👟 *SNKR est en ligne !*\n\n"
        "Je scanne Vinted & StockX pour trouver les meilleures affaires Nike, Jordan et New Balance.\n\n"
        f"🎯 *Marge minimum :* {MARGE_MINIMUM}€\n"
        "⏰ *Scan automatique :* 3x par jour (9h, 13h, 18h)\n\n"
        "📋 *Commandes :*\n"
        "/scan — Lancer un scan immédiat\n"
        "/status — Vérifier que SNKR fonctionne\n"
        "/aide — Afficher l'aide\n\n"
        "👟 Prêt à trouver des pépites !",
        parse_mode="Markdown"
    )

async def scan_command(update, context):
    global CHAT_ID
    CHAT_ID = str(update.effective_chat.id)
    await send_deals(bot=context.bot, chat_id=CHAT_ID)

async def status_command(update, context):
    await update.message.reply_text(
        "✅ *SNKR est opérationnel !*\n\n"
        "🔍 Surveille : Vinted → StockX\n"
        "👟 Marques : Nike, Jordan, New Balance\n"
        f"💶 Marge minimum : {MARGE_MINIMUM}€\n"
        "⏰ Scans : 9h, 13h et 18h chaque jour",
        parse_mode="Markdown"
    )

async def aide_command(update, context):
    await update.message.reply_text(
        "📋 *Aide SNKR*\n\n"
        "/start — Démarrer le bot\n"
        "/scan — Scanner maintenant\n"
        "/status — Vérifier le statut\n"
        "/aide — Ce message\n\n"
        f"💶 Marge minimum configurée : {MARGE_MINIMUM}€\n\n"
        "⚠️ _Vérifie toujours les annonces avant d'acheter._",
        parse_mode="Markdown"
    )

async def message_handler(update, context):
    await update.message.reply_text(
        "Utilise /scan pour chercher des affaires, ou /aide pour les commandes. 👟"
    )

# ============================================================
# PLANIFICATEUR
# ============================================================
async def post_init(application):
    scheduler = AsyncIOScheduler(timezone="Europe/Paris")
    # Scan 3x par jour : 9h, 13h, 18h
    for hour in [9, 13, 18]:
        scheduler.add_job(
            send_deals,
            trigger="cron",
            hour=hour,
            minute=0,
            kwargs={"bot": application.bot, "chat_id": CHAT_ID}
        )
    scheduler.start()
    logger.info("⏰ Planificateur démarré — scans à 9h, 13h et 18h")

def main():
    logger.info("🚀 Démarrage de SNKR Bot...")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("aide", aide_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("✅ SNKR Bot est en ligne !")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
