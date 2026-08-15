const CATEGORY_NAMES: Record<string, string> = {
  modern: '现代本格',
  ancient: '古风悬疑',
  republic: '民国谍战',
  japanese: '日式推理',
  campus: '校园青春',
  仙侠: '仙侠',
  科幻: '科幻',
  西幻: '西幻',
  欧式推理: '欧式推理',
  恐怖志怪: '恐怖志怪',
}

export function categoryName(code?: string | null): string {
  if (!code) return '未分类'
  return CATEGORY_NAMES[code] || code
}

export function textSizeLabel(chars?: number): string {
  const n = chars || 0
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万字`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}千字`
  return `${n}字`
}

export function formatAct(act: number): string {
  return `第${act}幕`
}
