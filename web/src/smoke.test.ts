// AI-ASSISTED: smoke test for the Vitest, happy-dom and @vue/test-utils wiring.
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h, ref } from 'vue'

const Counter = defineComponent({
  setup() {
    const count = ref(0)
    return () =>
      h('button', { onClick: () => (count.value += 1) }, `clicked ${String(count.value)}`)
  },
})

describe('client test wiring', () => {
  it('runs in a DOM', () => {
    expect(document.createElement('div').tagName).toBe('DIV')
  })

  it('mounts a Vue component and reacts to a click', async () => {
    const wrapper = mount(Counter)
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toBe('clicked 1')
  })
})
