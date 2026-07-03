import re


class SmartSplitter:
    def __init__(self, max_size=1024, min_size=256):
        # Ensure min_size makes sense relative to max_size
        self.max_size = max_size
        self.min_size = min(min_size, max_size // 2)

        self.separators = [
            r"\n\n+",         # Paragraphs
            r"\n",            # Newlines
            r"(?<=[.!?]) +",  # Sentences
            r"\|",            # Pipes (MediaWiki)
            r" +",            # Words
        ]

    def split(self, text: str) -> list[str]:
        if not text:
            return []

        # cleanup extra whitespaces or newlines
        text = re.sub(r"(\n\n)\s+|(\s)\s+", r"\1", text).strip(" \n\r\t")

        # 1. Recursive Binary Split with "Safe Zones"
        # fragments must not be longer than max size, but may be smaller than min size
        fragments = self._initial_split(text)

        # 2. Greedy Merge
        # merges fragments that are smaller than min size to bigger fragments that are just less than max size
        chunks = self._greedy_merge(fragments)

        # 3. Re-balancing Pass
        # fixes last chunk being too small (we merged all the prevous fragments and the last fragments are merged into a small chunk)
        return self._rebalance(chunks)

    def _initial_split(self, text: str) -> list[str]:
        stack = [text]
        done = []

        while stack:
            current = stack.pop()
            if len(current) <= self.max_size:
                done.append(current)
                continue

            # Try to find a "Safe Split" (respects min_size on both sides)
            split_idx = self._find_best_split_point(current, safe=True)

            # Fallback: If no safe split exists, take the best available split
            if split_idx is None:
                split_idx = self._find_best_split_point(current, safe=False)

            left, right = current[:split_idx], current[split_idx:]
            stack.append(right)
            stack.append(left)

        return done

    def _find_best_split_point(self, text: str, safe: bool = True) -> int | None:
        mid = len(text) // 2

        for sep in self.separators:
            matches = list(re.finditer(sep, text))

            if safe:
                # A "Safe" index ensures both resulting chunks are >= min_size
                indices = [m.end() for m in matches if self.min_size <= m.end() <= len(text) - self.min_size]
            else:
                # A "Forced" index just avoids the absolute 0 or length
                indices = [m.end() for m in matches if 0 < m.end() < len(text)]

            if indices:
                return min(indices, key=lambda x: abs(x - mid))

        # If forced and no separator found, split exactly at middle
        return mid if not safe else None

    def _greedy_merge(self, fragments: list[str]) -> list[str]:
        if not fragments:
            return []
        merged = []
        current = fragments[0]

        for i in range(1, len(fragments)):
            f = fragments[i]
            if len(current) + len(f) <= self.max_size:
                current += f
            else:
                merged.append(current)
                current = f
        merged.append(current)
        return merged

    def _rebalance(self, chunks: list[str]) -> list[str]:
        """
        If the last chunk is too small, merge it with the previous and 
        re-split that combined block at the absolute best middle.
        """
        if len(chunks) < 2:
            return chunks

        # Check if the last chunk violates min_size
        if len(chunks[-1]) < self.min_size:
            last = chunks.pop()
            prev = chunks.pop()
            combined = prev + last

            # Case A: Combined is small enough to be one chunk
            if len(combined) <= self.max_size:
                chunks.append(combined)
            else:
                # Case B: Combined is too big; split it exactly in the middle
                # (ignoring safety) to create two balanced, large-enough chunks.
                split_idx = self._find_best_split_point(combined, safe=False)
                chunks.append(combined[:split_idx])
                chunks.append(combined[split_idx:])

        return chunks
