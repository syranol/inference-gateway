from __future__ import annotations

from dataclasses import dataclass


OPEN_ANALYSIS = "<analysis>"
CLOSE_ANALYSIS = "</analysis>"
OPEN_FINAL = "<final>"
CLOSE_FINAL = "</final>"


@dataclass
class ParseResult:
    analysis_chunks: list[str]
    final_chunks: list[str]
    analysis_done: bool
    final_done: bool


class TagParser:
    """Incremental parser that splits a stream into <analysis> and <final> sections."""

    def __init__(self) -> None:
        self._state = "unknown"
        self._carry = ""
        self.seen_any_tag = False
        self.seen_final = False

    def feed(self, text: str) -> ParseResult:
        """Consume streamed text and return any completed analysis/final chunks."""
        self._carry += text
        analysis_chunks: list[str] = []
        final_chunks: list[str] = []
        analysis_done = False
        final_done = False

        while True:
            if self._state == "unknown":
                idx_a = self._carry.find(OPEN_ANALYSIS)
                idx_f = self._carry.find(OPEN_FINAL)
                if idx_a == -1 and idx_f == -1:
                    break
                if idx_a != -1 and (idx_f == -1 or idx_a < idx_f):
                    self.seen_any_tag = True
                    self._carry = self._carry[idx_a + len(OPEN_ANALYSIS) :]
                    self._state = "analysis"
                    continue
                self.seen_any_tag = True
                self._carry = self._carry[idx_f + len(OPEN_FINAL) :]
                self._state = "final"
                continue

            if self._state == "analysis":
                idx = self._carry.find(CLOSE_ANALYSIS)
                if idx == -1:
                    safe_len = max(0, len(self._carry) - len(CLOSE_ANALYSIS) + 1)
                    if safe_len:
                        analysis_chunks.append(self._carry[:safe_len])
                        self._carry = self._carry[safe_len:]
                    break
                analysis_chunks.append(self._carry[:idx])
                self._carry = self._carry[idx + len(CLOSE_ANALYSIS) :]
                self._state = "unknown"
                analysis_done = True
                continue

            if self._state == "final":
                idx = self._carry.find(CLOSE_FINAL)
                if idx == -1:
                    safe_len = max(0, len(self._carry) - len(CLOSE_FINAL) + 1)
                    if safe_len:
                        final_chunks.append(self._carry[:safe_len])
                        self._carry = self._carry[safe_len:]
                    break
                final_chunks.append(self._carry[:idx])
                self._carry = self._carry[idx + len(CLOSE_FINAL) :]
                self._state = "done"
                self.seen_final = True
                final_done = True
                break

            if self._state == "done":
                self._carry = ""
                break

        return ParseResult(
            analysis_chunks=analysis_chunks,
            final_chunks=final_chunks,
            analysis_done=analysis_done,
            final_done=final_done,
        )

    def finalize(self) -> ParseResult:
        """Flush remaining buffered content at the end of the stream."""
        analysis_chunks: list[str] = []
        final_chunks: list[str] = []
        analysis_done = False
        final_done = False

        if self._state == "analysis" and self._carry:
            analysis_chunks.append(self._carry)
            self._carry = ""
            analysis_done = True
        elif self._state == "final" and self._carry:
            final_chunks.append(self._carry)
            self._carry = ""
        elif self._state == "done":
            final_done = True

        return ParseResult(
            analysis_chunks=analysis_chunks,
            final_chunks=final_chunks,
            analysis_done=analysis_done,
            final_done=final_done,
        )
