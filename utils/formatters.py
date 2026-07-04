from datetime import datetime


def format_github_profile(user: dict, stats: dict) -> str:
    """
    Форматирует профиль разработчика GitHub в красивый текст для Telegram.

    Args:
        user: Данные пользователя от GitHub API
        stats: Статистика репозиториев от analyze_repos()

    Returns:
        str: Готовый Markdown-текст для отправки в Telegram
    """
    name = user.get("name") or user.get("login")
    login = user.get("login")
    bio = user.get("bio") or "—"
    location = user.get("location") or "—"
    company = user.get("company") or "—"
    blog = user.get("blog") or "—"
    followers = user.get("followers", 0)
    following = user.get("following", 0)
    public_repos = user.get("public_repos", 0)
    public_gists = user.get("public_gists", 0)
    twitter = user.get("twitter_username")

    # Форматируем дату регистрации
    created_at = user.get("created_at", "")
    if created_at:
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
            created_str = dt.strftime("%d.%m.%Y")
        except Exception:
            created_str = "—"
    else:
        created_str = "—"

    lines = [
        f"👤 *{name}* (`{login}`)",
        f"",
        f"📝 Bio: {bio}",
        f"📍 Локация: {location}",
        f"🏢 Компания: {company}",
    ]

    if blog and blog != "—":
        lines.append(f"🔗 Сайт: {blog}")
    if twitter:
        lines.append(f"🐦 Twitter: @{twitter}")

    lines += [
        f"",
        f"📅 На GitHub с: {created_str}",
        f"👥 Подписчики: *{followers}* | Подписки: {following}",
        f"📦 Публичных репо: *{public_repos}* | Gists: {public_gists}",
    ]

    # Добавляем статистику репозиториев, если есть
    if stats:
        lines.append("")
        lines.append("📊 *Статистика репозиториев:*")
        lines.append(f"⭐ Всего звёзд: *{stats['total_stars']}*")
        lines.append(f"🍴 Всего форков: *{stats['total_forks']}*")
        lines.append(f"📁 Оригинальных: {stats['original_count']} | Форков: {stats['fork_count']}")

        if stats.get("languages"):
            langs = " · ".join([f"{lang} ({count})" for lang, count in stats["languages"]])
            lines.append(f"💻 Языки: {langs}")

        if stats.get("topics"):
            topics = " ".join([f"`{topic}`" for topic in stats["topics"][:6]])
            lines.append(f"🏷 Топики: {topics}")

    return "\n".join(lines)


def format_github_repos(repos_stats: dict, username: str) -> str:
    """
    Форматирует топ-репозитории разработчика в красивый текст.

    Args:
        repos_stats: Статистика репозиториев от analyze_repos()
        username: Никнейм пользователя

    Returns:
        str: Готовый Markdown-текст для отправки в Telegram
    """
    if not repos_stats or not repos_stats.get("top_repos"):
        return "📭 Репозиториев не найдено."

    lines = [f"📁 *Топ репозитории {username}:*\n"]

    for i, repo in enumerate(repos_stats["top_repos"], 1):
        repo_name = repo.get("name", "")
        description = repo.get("description") or "без описания"
        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)
        language = repo.get("language") or "—"
        url = repo.get("html_url", "")
        updated = repo.get("updated_at", "")

        # Форматируем дату обновления
        if updated:
            try:
                dt = datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ")
                updated_str = dt.strftime("%d.%m.%Y")
            except Exception:
                updated_str = "—"
        else:
            updated_str = "—"

        # Обрезаем длинные описания
        if len(description) > 80:
            description = description[:80] + "..."

        lines.append(
            f"*{i}. [{repo_name}]({url})*\n"
            f"   📝 {description}\n"
            f"   ⭐ {stars} · 🍴 {forks} · 💻 {language} · 🕓 {updated_str}\n"
        )

    return "\n".join(lines)


def format_github_activity(activity: dict, username: str) -> str:
    """
    Форматирует активность пользователя в текст с визуальными индикаторами.

    Args:
        activity: Статистика активности от analyze_activity()
        username: Никнейм пользователя

    Returns:
        str: Готовый Markdown-текст для отправки в Telegram
    """
    if not activity:
        return f"📭 Нет публичной активности у {username}."

    lines = [f"📈 *Последняя активность {username}:*\n"]

    for label, count in activity.items():
        # Создаём визуальный бар длиной 10 символов
        bar = "▓" * min(count, 10) + "░" * (10 - min(count, 10))
        lines.append(f"{label}: {bar} {count}")

    return "\n".join(lines)


def format_github_compare(user1: dict, stats1: dict, user2: dict, stats2: dict) -> str:
    """
    Форматирует сравнение двух разработчиков в виде спортивного поединка.

    Args:
        user1: Данные первого пользователя
        stats1: Статистика первого пользователя
        user2: Данные второго пользователя
        stats2: Статистика второго пользователя

    Returns:
        str: Готовый Markdown-текст для отправки в Telegram
    """

    def get_value(user, stats, key):
        """Извлекает значение метрики в зависимости от ключа."""
        if key == "stars":
            return stats.get("total_stars", 0) if stats else 0
        if key == "repos":
            return user.get("public_repos", 0)
        if key == "followers":
            return user.get("followers", 0)
        if key == "forks":
            return stats.get("total_forks", 0) if stats else 0
        return 0

    # Метрики для сравнения
    metrics = [
        ("⭐ Звёзды", "stars"),
        ("📦 Репозитории", "repos"),
        ("👥 Подписчики", "followers"),
        ("🍴 Форки", "forks"),
    ]

    login1 = user1.get("login", "User1")
    login2 = user2.get("login", "User2")

    lines = [f"⚔️ *Сравнение: {login1} vs {login2}*\n"]

    score1, score2 = 0, 0

    for label, key in metrics:
        value1 = get_value(user1, stats1, key)
        value2 = get_value(user2, stats2, key)

        if value1 > value2:
            winner = f"✅ {login1}"
            score1 += 1
        elif value2 > value1:
            winner = f"✅ {login2}"
            score2 += 1
        else:
            winner = "🤝 Ничья"

        lines.append(f"{label}: *{value1}* vs *{value2}* → {winner}")

    lines.append(f"\n🏆 Итог: {login1} {score1}:{score2} {login2}")

    if score1 > score2:
        lines.append(f"🥇 Победитель: *{login1}*")
    elif score2 > score1:
        lines.append(f"🥇 Победитель: *{login2}*")
    else:
        lines.append("🤝 Ничья!")

    return "\n".join(lines)