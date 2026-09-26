export const EASE = [0.22, 1, 0.36, 1]

export const pillTransition = {
  width: { duration: 0.75, ease: EASE, delay: 0.1 },
  scale: { duration: 0.55, ease: EASE, times: [0, 0.55, 1] },
  opacity: { duration: 0.15 },
}
