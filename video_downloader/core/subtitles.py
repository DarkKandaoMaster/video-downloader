def subtitle_result_has_file(output):
    """判断 yt-dlp 输出是否表明已经写出或命中已有字幕文件。"""
    return (
        "Writing video subtitles to:" in output
        or ("Video subtitle " in output and " is already present" in output)
    )


def subtitle_result_has_no_match(output):
    """判断 yt-dlp 输出是否表明没有匹配请求语言的字幕。"""
    normalized = output.lower()
    return (
        "there are no subtitles for the requested languages" in normalized
        or "skipping writing video subtitles" in normalized
    )


def classify_subtitle_result(returncode, output):
    """把 yt-dlp 字幕命令结果分成 success / missing / error。"""
    if returncode != 0:
        return "error"
    if subtitle_result_has_file(output):
        return "success"
    if subtitle_result_has_no_match(output):
        return "missing"
    return "missing"
