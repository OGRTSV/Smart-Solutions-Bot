"""Тест подключения к DeepSeek API."""
import asyncio
from utils.ai_analyzer import test_deepseek_connection


async def main():
    print("Тестируем подключение к DeepSeek...")
    result = await test_deepseek_connection()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())