// AI-ASSISTED: the countdown's frame loop on requestAnimationFrame (UI spec §5.3).
import { onBeforeUnmount, readonly, ref, watch, type Ref } from 'vue'

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
