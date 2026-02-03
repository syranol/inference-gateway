# Python Asyncio vs Trio, and httpx vs aiohttp

## a) Await yielding: asyncio vs Trio (pros & cons)

**Pro 1 (asyncio fast‑path, fewer checkpoints)**  
Awaiting an already‑done future does **not** yield, avoiding an extra loop tick. Good for tight latency loops.
```python
import asyncio

async def main():
    fut = asyncio.get_running_loop().create_future()
    fut.set_result(123)
    x = await fut          # returns immediately; no scheduler checkpoint
    print(x)

asyncio.run(main())
```

**Pro 2 (asyncio allows tiny “mostly non‑preemptible” sections)**  
Uncontended locks/queues often complete without yielding, so you can keep very small critical paths jitter‑free.
```python
lock = asyncio.Lock()

async def bump(shared):
    await lock.acquire()   # if free, typically no yield
    try:
        shared["n"] += 1   # minimal critical section
    finally:
        lock.release()
```

**Con 1 (asyncio can starve the loop)**  
If an awaited call never actually blocks, the loop may never switch tasks.
```python
async def no_yield():  # completes instantly
    return

async def ticker():
    while True:
        print("tick"); await asyncio.sleep(0.5)

async def main():
    asyncio.create_task(ticker())
    while True:
        await no_yield()   # loop never yields → ticker starves

# fix: add explicit checkpoint, e.g., await asyncio.sleep(0)
```

**Con 2 (yield/cancel points are state‑dependent)**  
Whether `await q.get()` yields depends on runtime state (empty or not), making scheduling/cancellation harder to reason about from code alone.
```python
async def consumer(q: asyncio.Queue):
    while True:
        item = await q.get()   # yields only when empty
        handle(item)
        await asyncio.sleep(0) # explicit checkpoint to share CPU
```

**Contrast with Trio:** Trio’s APIs aim to checkpoint on (almost) every async call for predictability; e.g. `await trio.sleep_until(past_time)` still yields. That reduces starvation surprises but adds a bit of per‑await overhead.

---

## b) Why aiohttp often outperforms httpx under high concurrency

**Root architectural difference (biggest factor):**  
`httpx` layers `httpx → httpcore → AnyIO → backend (asyncio/Trio)` and historically used AnyIO’s Trio‑like cancel/coordination semantics plus pure‑Python `h11` for HTTP/1.1. This extra abstraction adds per‑request CPU + sync overhead.  
`aiohttp` is asyncio‑native and leans on optimized C parsing (`llhttp`) and tight coupling to asyncio transports, giving a leaner hot path.

**Most impactful performance factor:** per‑request coordination overhead in httpx/httpcore (AnyIO + abstraction) becomes dominant at high concurrency. Benchmarks and maintainer notes show replacing AnyIO paths with native asyncio primitives yields ~3×+ speedups and smoother latency.

**Mitigations**
- **httpx/httpcore:** added native asyncio backend and swapped AnyIO locks/queues for asyncio primitives to cut overhead; continuing to reduce abstraction in hot paths.
- **aiohttp:** ships/uses C‑accelerated HTTP parsing (llhttp) and optimized request/response lifecycle; avoiding Python‑level parsing cost further improves throughput.

**Practical takeaway for LLM clients:** For heavy fan-out async calls, aiohttp (or httpx with the native asyncio backend) typically delivers better throughput/latency. If portability to Trio is required, httpx remains attractive; if raw asyncio performance is paramount, aiohttp often wins.

## AI assistance
AI was used as a research and review aid (not as an autonomous code generator). I used it to:
- Upskill quickly on asyncio vs Trio semantics and the httpx/aiohttp performance debate.
- Compare pros/cons and gather benchmark notes to justify the explanations above.
- Sanity-check code snippets and phrasing for clarity and concision.
All technical decisions, wording, and edits were written and integrated by me.
