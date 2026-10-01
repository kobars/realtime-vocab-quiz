// AI-ASSISTED: frame loops for the question screens: the count-up of scores and the countdown, both on requestAnimationFrame (UI spec §5.2, §5.3).
import { usePreferredReducedMotion } from '@vueuse/core'
import { onBeforeUnmount, readonly, ref, watch, type Ref } from 'vue'

export const COUNT_MS = 600

/**
 * A number that counts up from `from` to `target()` over 600 ms with an ease-out, and again on each later change
 * (UI spec §5.2). With reduced motion, or when the value goes down, it shows the end value at once.
 */
export function useCountUp(target: () => number, from = target()): Readonly<Ref<number>> {
  const reduced = usePreferredReducedMotion()
  const shown = ref(from)
  let frame = 0
  function run(to: number): void {
    cancelAnimationFrame(frame)
    const start = performance.now()
    const begin = shown.value
    if (reduced.value === 'reduce' || to <= begin) return void (shown.value = to)
    const step = () => {
      const p = Math.min(1, (performance.now() - start) / COUNT_MS)
      shown.value = Math.round(begin + (to - begin) * (1 - (1 - p) ** 3))
      if (p < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
  }
  watch(target, run)
  run(target())
  onBeforeUnmount(() => cancelAnimationFrame(frame))
  return readonly(shown)
}

/** `msLeft()` read on every frame until it reaches 0, restarted when `key()` changes (a new deadline). */
export function useCountdown(msLeft: () => number, key: () => unknown): Readonly<Ref<number>> {
  const left = ref(msLeft())
  let frame = 0
  const tick = () => {
    left.value = msLeft()
    if (left.value > 0) frame = requestAnimationFrame(tick)
  }
  watch(key, () => (cancelAnimationFrame(frame), tick()), { immediate: true })
  onBeforeUnmount(() => cancelAnimationFrame(frame))
  return readonly(left)
}
