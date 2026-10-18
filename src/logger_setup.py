import json
import threading

from langchain_core.tracers.base import BaseTracer

_lock = threading.Lock()


def _short(obj, n: int = 1500) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)[:n]


class FileTracer(BaseTracer):
    """
    Writes the whole run tree
    (chains, LLM calls, tools)
    to a text file when a root run ends.
    """

    def __init__(self, path: str = "log.txt", **kwargs):
        super().__init__(**kwargs)
        self.path = path

    def _persist_run(self, run) -> None:
        with _lock, open(self.path, "a", encoding="utf-8") as f:
            self._dump(run, f, 0)
            f.write("\n" + "=" * 80 + "\n\n")

    def _dump(self, run, f, depth: int) -> None:
        pad = "  " * depth
        secs = (
            run.end_time - run.start_time
            ).total_seconds() if run.end_time else 0
        f.write(
            f"{pad}[{run.run_type}] {run.name} | {secs:.1f}s | error={run.error}\n"
            )
        if run.run_type in ("llm", "chat_model", "tool"):
            f.write(f"{pad}  in : {_short(run.inputs)}\n")
            f.write(f"{pad}  out: {_short(run.outputs)}\n")
        for child in run.child_runs:
            self._dump(child, f, depth + 1)
