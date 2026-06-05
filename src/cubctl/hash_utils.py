"""Timeline hash helpers (mirrors CUB client JS implementation)."""


def timecode_hash(value: str) -> str:
    """Compute a 32-bit string hash for timeline keys."""
    text = (value or "") + ""
    result = 0
    if not text:
        return str(result)
    for char in text:
        result = ((result << 5) - result) + ord(char)
        result &= 0xFFFFFFFF
        if result >= 0x80000000:
            result -= 0x100000000
    return str(abs(result))


def movie_timecode_hash(original_title: str) -> str:
    return timecode_hash(original_title)


def tv_timecode_hash(season: int, episode: int, original_name: str) -> str:
    separator = ":" if season > 10 else ""
    return timecode_hash(f"{season}{separator}{episode}{original_name}")
