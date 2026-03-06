import os
import discord
from dotenv import load_dotenv
import asyncio

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

class DebugBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True # 핵심!
        super().__init__(intents=intents)

    async def on_ready(self):
        print(f'✅ 진단 봇 로그인: {self.user}')
        with open('discord_debug.txt', 'a', encoding='utf-8') as f:
            f.write(f"\n--- Bot Started: {self.user} ---\n")

    async def on_message(self, message):
        if message.author == self.user: return
        
        log_msg = f"📩 수신! [채널:{message.channel.name}({message.channel.id})] [작성자:{message.author}] 내용: {message.content}\n"
        print(log_msg)
        
        # 파일에 즉시 기록
        with open('discord_debug.txt', 'a', encoding='utf-8') as f:
            f.write(log_msg)
            
        # 디스코드에 반응 테스트
        await message.add_reaction('👀')

async def main():
    bot = DebugBot()
    await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())
