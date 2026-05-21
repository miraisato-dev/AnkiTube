# filters.py

def format_time(seconds):
    try:
        sec = float(seconds)
        minutes = int(sec // 60)
        remaining_sec = int(sec % 60)
        # 01:23 の形式にする
        return f"{minutes:02}:{remaining_sec:02}"
    except (ValueError, TypeError):
        return seconds # 変換できない時はそのまま出す