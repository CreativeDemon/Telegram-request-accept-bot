import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ChatJoinRequestHandler,
    CallbackQueryHandler
)
import json
import os
import datetime
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Data storage files
USERS_FILE = 'users.json'
CHANNELS_FILE = 'channels.json'
ADMINS_FILE = 'admins.json'
BROADCASTS_FILE = 'broadcasts.json'

# Initialize data files
def init_data_files():
    for file in [USERS_FILE, CHANNELS_FILE, ADMINS_FILE, BROADCASTS_FILE]:
        if not os.path.exists(file):
            with open(file, 'w') as f:
                json.dump([], f)

init_data_files()

# Bot configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")
    
ADMIN_IDS = [1524473035]  # Replace with your admin user ID(s)

# Helper functions
def read_json(file: str) -> List[Dict]:
    with open(file, 'r') as f:
        return json.load(f)

def write_json(file: str, data: List[Dict]):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

def save_user(user_id: int, username: str, first_name: str, last_name: str, channel_id: int, channel_title: str):
    users = read_json(USERS_FILE)
    
    # Check if user exists
    user_exists = False
    for user in users:
        if user['user_id'] == user_id:
            user_exists = True
            # Add channel if not already there
            if channel_id not in user['approved_channels']:
                user['approved_channels'].append(channel_id)
            break
    
    if not user_exists:
        # New user
        users.append({
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'join_date': str(datetime.datetime.now()),
            'approved_channels': [channel_id]
        })
    
    write_json(USERS_FILE, users)
    
    # Save channel info if not exists
    channels = read_json(CHANNELS_FILE)
    channel_exists = any(channel['channel_id'] == channel_id for channel in channels)
    if not channel_exists:
        channels.append({
            'channel_id': channel_id,
            'title': channel_title,
            'username': f"channel_{channel_id}",
            'join_date': str(datetime.datetime.now())
        })
        write_json(CHANNELS_FILE, channels)

async def approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.chat_join_request.from_user.id
    username = update.chat_join_request.from_user.username or "No username"
    first_name = update.chat_join_request.from_user.first_name or ""
    last_name = update.chat_join_request.from_user.last_name or ""
    channel_id = update.chat_join_request.chat.id
    channel_title = update.chat_join_request.chat.title or f"Channel {channel_id}"
    
    try:
        # Approve the join request
        await update.chat_join_request.approve()
        
        # Log the approval
        logger.info(f"Approved join request for user {user_id} (@{username}) in channel {channel_id} ({channel_title})")
        
        # Save user data
        save_user(user_id, username, first_name, last_name, channel_id, channel_title)
        
        # Send approval notification
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Your join request for *{channel_title}* has been approved!\n\nWelcome!",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Could not send approval notification to user {user_id}: {e}")
            
    except Exception as e:
        logger.error(f"Error approving user {user_id} for channel {channel_id}: {e}")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Auto-Approval Bot*\n\n"
        "This bot automatically approves join requests in channels where it's an admin.\n\n"
        "Admin commands:\n"
        "/broadcast - Send a broadcast message\n"
        "/stats - Show broadcast statistics",
        parse_mode='Markdown'
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    
    await update.message.reply_text(
        "📢 Please send the message you want to broadcast.\n\n"
        "You can include:\n"
        "- Text with Markdown formatting\n"
        "- A photo with caption\n"
        "- A message with buttons\n"
        "- Other media types\n\n"
        "Send /cancel at any time to stop the broadcast.",
        parse_mode='Markdown'
    )
    
    # Set state to wait for broadcast message
    context.user_data['awaiting_broadcast'] = True

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'broadcast_in_progress' in context.user_data:
        context.user_data['broadcast_cancelled'] = True
        await update.message.reply_text("Broadcast cancelled. Partial results:")
        await show_broadcast_stats(update, context)
    elif 'awaiting_broadcast' in context.user_data:
        del context.user_data['awaiting_broadcast']
        await update.message.reply_text("Broadcast preparation cancelled.")
    else:
        await update.message.reply_text("No broadcast to cancel.")

async def show_broadcast_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'broadcast_stats' not in context.user_data:
        await update.message.reply_text("No broadcast statistics available.")
        return
    
    stats = context.user_data['broadcast_stats']
    stats_message = (
        "📊 *Broadcast Progress*\n\n"
        f"◇ Total Users: {stats['total_users']}\n"
        f"◇ Successful: {stats['successful']}\n"
        f"◇ Blocked Users: {stats['blocked']}\n"
        f"◇ Deleted Accounts: {stats['deleted']}\n"
        f"◇ Unsuccessful: {stats['unsuccessful']}"
    )
    
    await update.message.reply_text(stats_message, parse_mode='Markdown')

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast', False):
        return
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    # Clear the preparation state
    del context.user_data['awaiting_broadcast']
    
    # Get all users
    users = read_json(USERS_FILE)
    
    if not users:
        await update.message.reply_text("No users in database to broadcast to.")
        return
    
    total_users = len(users)
    successful = 0
    blocked = 0
    deleted = 0
    unsuccessful = 0
    
    # Store stats in user_data for cancellation
    context.user_data['broadcast_stats'] = {
        'total_users': total_users,
        'successful': successful,
        'blocked': blocked,
        'deleted': deleted,
        'unsuccessful': unsuccessful
    }
    context.user_data['broadcast_in_progress'] = True
    context.user_data['broadcast_cancelled'] = False
    
    # Prepare the message based on type
    message = update.message
    reply_markup = message.reply_markup
    
    # Send progress message
    progress_msg = await update.message.reply_text(
        "📤 Starting broadcast...\n"
        f"0/{total_users} (0%)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel Broadcast", callback_data="cancel_broadcast")]
        ])
    )
    
    # Send to each user
    for i, user in enumerate(users):
        if context.user_data.get('broadcast_cancelled', False):
            break
        
        try:
            if message.text:
                await context.bot.send_message(
                    chat_id=user['user_id'],
                    text=message.text_markdown_v2,
                    parse_mode='MarkdownV2',
                    reply_markup=reply_markup
                )
            elif message.photo:
                await context.bot.send_photo(
                    chat_id=user['user_id'],
                    photo=message.photo[-1].file_id,
                    caption=message.caption_markdown_v2 if message.caption else None,
                    parse_mode='MarkdownV2',
                    reply_markup=reply_markup
                )
            elif message.video:
                await context.bot.send_video(
                    chat_id=user['user_id'],
                    video=message.video.file_id,
                    caption=message.caption_markdown_v2 if message.caption else None,
                    parse_mode='MarkdownV2',
                    reply_markup=reply_markup
                )
            
            successful += 1
            
        except Exception as e:
            error_msg = str(e).lower()
            if "blocked" in error_msg:
                blocked += 1
            elif "deleted" in error_msg or "not found" in error_msg:
                deleted += 1
            else:
                unsuccessful += 1
            logger.error(f"Error sending to user {user['user_id']}: {e}")
        
        # Update progress every 10 messages or last message
        if i % 10 == 0 or i == len(users) - 1:
            context.user_data['broadcast_stats'] = {
                'total_users': total_users,
                'successful': successful,
                'blocked': blocked,
                'deleted': deleted,
                'unsuccessful': unsuccessful
            }
            
            percentage = int((i + 1) / total_users * 100)
            try:
                await progress_msg.edit_text(
                    f"📤 Broadcasting...\n"
                    f"{i + 1}/{total_users} ({percentage}%)\n\n"
                    f"✅ {successful} successful\n"
                    f"🚫 {blocked + deleted + unsuccessful} failed",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Cancel Broadcast", callback_data="cancel_broadcast")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error updating progress message: {e}")
    
    # Clean up
    del context.user_data['broadcast_in_progress']
    
    # Save broadcast stats if not cancelled
    if not context.user_data.get('broadcast_cancelled', False):
        broadcasts = read_json(BROADCASTS_FILE)
        
        message_type = "text"
        if message.photo:
            message_type = "photo"
        elif message.video:
            message_type = "video"
        
        broadcasts.append({
            'admin_id': user_id,
            'message_type': message_type,
            'sent_date': str(datetime.datetime.now()),
            'total_users': total_users,
            'successful': successful,
            'blocked': blocked,
            'deleted': deleted,
            'unsuccessful': unsuccessful
        })
        
        write_json(BROADCASTS_FILE, broadcasts)
    
    # Remove the cancel button from progress message
    try:
        await progress_msg.edit_text(
            "📤 Broadcast completed!\n"
            f"{total_users} users processed",
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Error updating final progress message: {e}")
    
    # Send broadcast summary
    await show_broadcast_stats(update, context)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_broadcast":
        context.user_data['broadcast_cancelled'] = True
        await query.edit_message_text(
            "Broadcast cancelled by admin.",
            reply_markup=None
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this command.")
        return
    
    users = read_json(USERS_FILE)
    channels = read_json(CHANNELS_FILE)
    broadcasts = read_json(BROADCASTS_FILE)
    
    total_users = len(users)
    total_channels = len(channels)
    
    if not broadcasts:
        stats_message = (
            "📊 *Bot Statistics*\n\n"
            f"◇ Total Users: {total_users}\n"
            f"◇ Total Channels: {total_channels}\n"
            "◇ No broadcasts sent yet"
        )
    else:
        total_broadcasts = len(broadcasts)
        total_recipients = sum(b['total_users'] for b in broadcasts)
        total_successful = sum(b['successful'] for b in broadcasts)
        total_blocked = sum(b['blocked'] for b in broadcasts)
        total_deleted = sum(b['deleted'] for b in broadcasts)
        total_unsuccessful = sum(b['unsuccessful'] for b in broadcasts)
        
        stats_message = (
            "📊 *Bot Statistics*\n\n"
            f"◇ Total Users: {total_users}\n"
            f"◇ Total Channels: {total_channels}\n"
            f"◇ Total Broadcasts: {total_broadcasts}\n"
            f"◇ Total Recipients: {total_recipients}\n"
            f"◇ Total Successful: {total_successful}\n"
            f"◇ Total Blocked: {total_blocked}\n"
            f"◇ Total Deleted: {total_deleted}\n"
            f"◇ Total Unsuccessful: {total_unsuccessful}"
        )
    
    await update.message.reply_text(stats_message, parse_mode='Markdown')

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("cancel", cancel_broadcast))
    
    # Message handler for broadcast content
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND,
        handle_broadcast_message
    ))
    
    # Button handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Join request handler
    application.add_handler(ChatJoinRequestHandler(approve_user))
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()