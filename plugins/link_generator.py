from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from helper.helper_func import encode, get_message_id
from config import LOGGER
import asyncio


async def _snapshot_range(client, source_channel_id, full_range):
    """Resolve a range NOW into (survivors, missing), order preserved. Never raises."""
    try:
        probed = await client.get_messages(chat_id=source_channel_id, message_ids=list(full_range))
    except FloodWait as e:
        await asyncio.sleep(e.x)
        try:
            probed = await client.get_messages(chat_id=source_channel_id, message_ids=list(full_range))
        except Exception as e2:
            client.LOGGER(__name__, client.name).warning(f"Batch snapshot retry failed: {e2}")
            return [], list(full_range)
    except Exception as e:
        client.LOGGER(__name__, client.name).warning(f"Batch snapshot failed: {e}")
        return [], list(full_range)
    found = {m.id for m in (probed or []) if m is not None}
    survivors = [mid for mid in full_range if mid in found]
    missing = [mid for mid in full_range if mid not in found]
    return survivors, missing


def _batch_link_text(link, survivors, missing):
    text = f"<blockquote>✓ ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʙᴀᴛᴄʜ ʟɪɴᴋ</blockquote>\n\n<code>{link}</code>"
    if missing:
        text += f"\n\n⚠️ {len(missing)} of {len(survivors) + len(missing)} file(s) in this range were already gone and were skipped."
    return text

async def get_db_channels_info(client):
    """Get formatted database channels information with links"""
    db_channels = getattr(client, 'db_channels', {})
    primary_db = getattr(client, 'primary_db_channel', client.db)
    
    if not db_channels:
        # If no additional DB channels, show primary only
        try:
            primary_chat = await client.get_chat(primary_db)
            if hasattr(primary_chat, 'invite_link') and primary_chat.invite_link:
                return f"<blockquote>✦ ᴘʀɪᴍᴀʀʏ ᴅʙ ᴄʜᴀɴɴᴇʟ: <a href='{primary_chat.invite_link}'>{primary_chat.title}</a></blockquote>"
            else:
                return f"<blockquote>✦ ᴘʀɪᴍᴀʀʏ ᴅʙ ᴄʜᴀɴɴᴇʟ: {primary_chat.title} (`{primary_db}`)</blockquote>"
        except:
            return f"<blockquote>✦ ᴘʀɪᴍᴀʀʏ ᴅʙ ᴄʜᴀɴɴᴇʟ: `{primary_db}`</blockquote>"
    
    # Format all DB channels with links
    channels_info = ["<blockquote>✦ ᴀᴠᴀɪʟᴀʙʟᴇ ᴅᴀᴛᴀʙᴀsᴇ ᴄʜᴀɴɴᴇʟs:</blockquote>"]
    for channel_id_str, channel_data in db_channels.items():
        channel_name = channel_data.get('name', 'ᴜɴᴋɴᴏᴡɴ')
        is_primary_text = "✦ ᴘʀɪᴍᴀʀʏ" if channel_data.get('is_primary', False) else "• sᴇᴄᴏɴᴅᴀʀʏ"
        
        try:
            chat = await client.get_chat(int(channel_id_str))
            if hasattr(chat, 'invite_link') and chat.invite_link:
                channels_info.append(f"{is_primary_text}: <a href='{chat.invite_link}'>{channel_name}</a>")
            else:
                channels_info.append(f"{is_primary_text}: {channel_name} (`{channel_id_str}`)")
        except:
            channels_info.append(f"{is_primary_text}: {channel_name} (`{channel_id_str}`)")
    
    return "\n".join(channels_info)

@Client.on_message(filters.private & filters.command('batch'))
async def batch(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    
    # Get all database channels with links
    db_channels_info = await get_db_channels_info(client)
    
    while True:
        try:
            first_message = await client.ask(
                text=f"""<blockquote>ꜰᴏʀᴡᴀʀᴅ ᴛʜᴇ ꜰɪʀsᴛ ᴍᴇssᴀɢᴇ ꜰʀᴏᴍ ᴅʙ ᴄʜᴀɴɴᴇʟ (ᴡɪᴛʜ ǫᴜᴏᴛᴇs)..</blockquote>
{db_channels_info}

<blockquote>ᴏʀ sᴇɴᴅ ᴛʜᴇ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴘᴏsᴛ ʟɪɴᴋ</blockquote>""",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except:
            return
        f_msg_id, source_channel_id = await get_message_id(client, first_message)
        if f_msg_id:
            break
        else:
            await first_message.reply("<blockquote>✗ ᴇʀʀᴏʀ</blockquote>\n\nᴛʜɪs ꜰᴏʀᴡᴀʀᴅᴇᴅ ᴘᴏsᴛ ɪs ɴᴏᴛ ꜰʀᴏᴍ ᴍʏ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴏʀ ᴛʜɪs ʟɪɴᴋ ɪs ᴛᴀᴋᴇɴ ꜰʀᴏᴍ ᴅʙ ᴄʜᴀɴɴᴇʟ", quote = True)
            continue

    while True:
        try:
            second_message = await client.ask(
                text=f"""<blockquote>ꜰᴏʀᴡᴀʀᴅ ᴛʜᴇ ʟᴀsᴛ ᴍᴇssᴀɢᴇ ꜰʀᴏᴍ ᴅʙ ᴄʜᴀɴɴᴇʟ (ᴡɪᴛʜ ǫᴜᴏᴛᴇs)..</blockquote>
{db_channels_info}

<blockquote>ᴏʀ sᴇɴᴅ ᴛʜᴇ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴘᴏsᴛ ʟɪɴᴋ</blockquote>""",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except:
            return
        s_msg_id, second_source = await get_message_id(client, second_message)  # We only need msg_id for second message
        if s_msg_id:
            if second_source != source_channel_id:
                await second_message.reply(
                    "<blockquote>✗ ᴇʀʀᴏʀ</blockquote>\n\nBoth messages must come from the SAME DB channel. "
                    "Forward first and last from one channel only.",
                    quote=True,
                )
                continue
            if s_msg_id < f_msg_id:
                await second_message.reply(
                    "<blockquote>✗ ᴇʀʀᴏʀ</blockquote>\n\nLast message must not be older than the first. Swap the order.",
                    quote=True,
                )
                continue
            if (s_msg_id - f_msg_id + 1) > 200:
                await second_message.reply(
                    "<blockquote>✗ ᴇʀʀᴏʀ</blockquote>\n\nBatch too large (max 200 files per link). Pick a shorter range.",
                    quote=True,
                )
                continue
            break
        else:
            await second_message.reply("<blockquote>✗ ᴇʀʀᴏʀ</blockquote>\n\nᴛʜɪs ꜰᴏʀᴡᴀʀᴅᴇᴅ ᴘᴏsᴛ ɪs ɴᴏᴛ ꜰʀᴏᴍ ᴍʏ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴏʀ ᴛʜɪs ʟɪɴᴋ ɪs ᴛᴀᴋᴇɴ ꜰʀᴏᴍ ᴅʙ ᴄʜᴀɴɴᴇʟ", quote = True)
            continue

    # Snapshot the range immediately: the link carries an explicit survivor list, not a blind range.
    full_range = list(range(f_msg_id, s_msg_id + 1))
    survivors, missing = await _snapshot_range(client, source_channel_id, full_range)
    if not survivors:
        return await second_message.reply_text(
            "<blockquote>✗ ɴᴏᴛʜɪɴɢ ᴛᴏ ʟɪɴᴋ</blockquote>\n\nEvery message in that range is already gone from storage.",
            quote=True,
        )
    client.LOGGER(__name__, client.name).info(f"Generating batch link with source channel: {source_channel_id}, survivors: {len(survivors)}, missing: {len(missing)}")
    batch_id = await client.mongodb.save_batch(source_channel_id, survivors, message.from_user.id, missing)
    string = f"batch-{batch_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 sʜᴀʀᴇ ᴜʀʟ", url=f'https://telegram.me/share/url?url={link}')]])
    await second_message.reply_text(_batch_link_text(link, survivors, missing), quote=True, reply_markup=reply_markup)

#===============================================================#

@Client.on_message(filters.private & filters.command('genlink'))
async def link_generator(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    
    # Get all database channels with links
    db_channels_info = await get_db_channels_info(client)
    
    while True:
        try:
            channel_message = await client.ask(
                text=f"""<blockquote>ꜰᴏʀᴡᴀʀᴅ ᴍᴇssᴀɢᴇ ꜰʀᴏᴍ ᴛʜᴇ ᴅʙ ᴄʜᴀɴɴᴇʟ (ᴡɪᴛʜ ǫᴜᴏᴛᴇs)..</blockquote>

{db_channels_info}

<blockquote>ᴏʀ sᴇɴᴅ ᴛʜᴇ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴘᴏsᴛ ʟɪɴᴋ</blockquote>""",
                chat_id=message.from_user.id,
                filters=(filters.forwarded | (filters.text & ~filters.forwarded)),
                timeout=60
            )
        except:
            return
        msg_id, source_channel_id = await get_message_id(client, channel_message)
        if msg_id:
            break
        else:
            await channel_message.reply("<blockquote>✗ ᴇʀʀᴏʀ</blockquote>\n\nᴛʜɪs ꜰᴏʀᴡᴀʀᴅᴇᴅ ᴘᴏsᴛ ɪs ɴᴏᴛ ꜰʀᴏᴍ ᴍʏ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴏʀ ᴛʜɪs ʟɪɴᴋ ɪs ɴᴏᴛ ᴛᴀᴋᴇɴ ꜰʀᴏᴍ ᴅʙ ᴄʜᴀɴɴᴇʟ", quote = True)
            continue

    base64_string = await encode(f"get-{msg_id * abs(source_channel_id)}")
    link = f"https://t.me/{client.username}?start={base64_string}"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 sʜᴀʀᴇ ᴜʀʟ", url=f'https://telegram.me/share/url?url={link}')]])
    await channel_message.reply_text(f"<blockquote>✓ ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ</blockquote>\n\n<code>{link}</code>", quote=True, reply_markup=reply_markup)

#===============================================================#

@Client.on_message(filters.private & filters.command("nbatch"))
async def nbatch(client: Client, message: Message):
    if message.from_user.id not in client.admins:
        return await message.reply(client.reply_text)
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("<blockquote>✗ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ!</blockquote> ᴜsᴇ: /nbatch {number}")
        return
    
    batch_size = int(args[1])
    if batch_size < 1 or batch_size > 200:
        await message.reply("<blockquote>✗ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ!</blockquote> ᴜsᴇ: /nbatch {1-200}")
        return
    
    # Get all database channels with links
    db_channels_info = await get_db_channels_info(client)
    
    while True:
        try:
            first_message = await client.ask(
                text=f"""<blockquote>🚀 sᴇɴᴅ ᴅʙ ᴄʜᴀɴɴᴇʟ ꜰɪʀsᴛ ᴍᴇssᴀɢᴇ ʟɪɴᴋ (ᴡɪᴛʜ ǫᴜᴏᴛᴇs)...</blockquote>

{db_channels_info}""",
                chat_id=message.from_user.id,
                filters=(filters.text & ~filters.forwarded),
                timeout=60
            )
        except:
            return
    
        f_msg_id, source_channel_id = await get_message_id(client, first_message)
        if f_msg_id:
            break
        else:
            await first_message.reply("<blockquote>😫 ɪɴᴠᴀʟɪᴅ!</blockquote> sᴇɴᴅ ᴄᴏʀʀᴇᴄᴛ ᴅʙ ᴄʜᴀɴɴᴇʟ ᴍᴇssᴀɢᴇ ʟɪɴᴋ.", quote=True)
            continue
    
    full_range = list(range(f_msg_id, f_msg_id + batch_size))
    survivors, missing = await _snapshot_range(client, source_channel_id, full_range)
    if not survivors:
        return await first_message.reply_text(
            "<blockquote>✗ ɴᴏᴛʜɪɴɢ ᴛᴏ ʟɪɴᴋ</blockquote>\n\nEvery message in that range is already gone from storage.",
            quote=True,
        )

    batch_id = await client.mongodb.save_batch(source_channel_id, survivors, message.from_user.id, missing)
    string = f"batch-{batch_id}"
    base64_string = await encode(string)
    link = f"https://t.me/{client.username}?start={base64_string}"
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📫 ʏᴏᴜʀ ʙᴀᴛᴄʜ ᴜʀʟ", url=f'https://telegram.me/share/url?url={link}')]
    ])
    
    await first_message.reply_text(_batch_link_text(link, survivors, missing), quote=True, reply_markup=reply_markup)    

