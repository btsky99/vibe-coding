import os
import discord
from dotenv import load_dotenv
import asyncio

# .env 로드
load_dotenv()

TOKEN = os.getenv('DISCORD_BOT_TOKEN')

class TestBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

    async def on_ready(self):
        print(f'✅ 디스코드 봇 로그인 성공: {self.user}')
        print(f'🤖 봇 ID: {self.user.id}')
        print('---')
        print('설정된 채널 확인 (T1~T8):')
        for i in range(1, 9):
            channel_id = os.getenv(f'DISCORD_CHANNEL_T{i}')
            if channel_id and channel_id != f'CHANNEL_ID_T{i}':
                channel = self.get_channel(int(channel_id))
                if channel:
                    print(f'  [T{i}] #{channel.name} (ID: {channel_id}) -> 연결됨')
                else:
                    print(f'  [T{i}] ID {channel_id} -> 채널을 찾을 수 없음')
            else:
                print(f'  [T{i}] 설정되지 않음')
        
        print('\n로그인 확인이 완료되었습니다. 5초 후 종료합니다.')
        await asyncio.sleep(5)
        await self.close()

async def main():
    if not TOKEN or TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print('❌ 에러: DISCORD_BOT_TOKEN이 설정되지 않았습니다.')
        return

    bot = TestBot()
    try:
        await bot.start(TOKEN)
    except Exception as e:
        print(f'❌ 로그인 실패: {e}')

if __name__ == '__main__':
    asyncio.run(main())
