import { ref, onMounted, onUnmounted, watch, type Ref } from 'vue'

declare global {
  interface Window {
    MathJax: {
      typesetPromise: () => Promise<void>
      [key: string]: any
    }
  }
}

export function useMathJax(targetRef: Ref<HTMLElement | null>) {
  const isLoaded = ref(false)

  function typeset() {
    if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
      window.MathJax.typesetPromise()
    }
  }

  let observer: MutationObserver | null = null

  onMounted(() => {
    if (window.MathJax) {
      isLoaded.value = true
    }

    watch(targetRef, (el) => {
      if (observer) observer.disconnect()
      if (!el) return
      observer = new MutationObserver(() => {
        typeset()
      })
      observer.observe(el, { childList: true, subtree: true, characterData: true })
    }, { immediate: true })
  })

  onUnmounted(() => {
    if (observer) observer.disconnect()
  })

  return { typeset, isLoaded }
}