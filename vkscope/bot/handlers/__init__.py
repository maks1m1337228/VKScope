from bot.handlers import analyze, callback, start

labelers = [start.labeler, analyze.labeler, callback.labeler]

__all__ = ["labelers", "start", "analyze", "callback"]
