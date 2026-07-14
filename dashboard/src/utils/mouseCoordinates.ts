export interface NormalizedPoint {
  x: number
  y: number
}

export function getNormalizedImageCoordinates(
  container: HTMLElement,
  image: HTMLImageElement,
  clientX: number,
  clientY: number,
): NormalizedPoint | null {
  const containerRect = container.getBoundingClientRect()
  const naturalWidth = image.naturalWidth
  const naturalHeight = image.naturalHeight

  if (!naturalWidth || !naturalHeight || containerRect.width <= 0 || containerRect.height <= 0) {
    return null
  }

  const containerAspect = containerRect.width / containerRect.height
  const imageAspect = naturalWidth / naturalHeight

  let renderWidth: number
  let renderHeight: number
  let offsetX: number
  let offsetY: number

  if (imageAspect > containerAspect) {
    renderWidth = containerRect.width
    renderHeight = containerRect.width / imageAspect
    offsetX = 0
    offsetY = (containerRect.height - renderHeight) / 2
  } else {
    renderHeight = containerRect.height
    renderWidth = containerRect.height * imageAspect
    offsetX = (containerRect.width - renderWidth) / 2
    offsetY = 0
  }

  const localX = clientX - containerRect.left - offsetX
  const localY = clientY - containerRect.top - offsetY

  if (localX < 0 || localY < 0 || localX > renderWidth || localY > renderHeight) {
    return null
  }

  return {
    x: Math.max(0, Math.min(1, localX / renderWidth)),
    y: Math.max(0, Math.min(1, localY / renderHeight)),
  }
}
