const FORBIDDEN_KEY_CODES = new Set([
  'MetaLeft',
  'MetaRight',
  'ControlLeft',
  'ControlRight',
  'AltLeft',
  'AltRight',
  'OSLeft',
  'OSRight',
  'ShiftLeft',
  'ShiftRight',
])

const ALLOWED_KEY_CODE_PATTERN = /^(Key[A-Z]|Digit[0-9]|F[1-9]|F1[0-2]|Arrow(?:Up|Down|Left|Right)|Enter|Backspace|Tab|Escape|Space|Delete|Insert|Home|End|PageUp|PageDown)$/

export function isAllowedKeyCode(code: string): boolean {
  if (!code || FORBIDDEN_KEY_CODES.has(code)) {
    return false
  }
  return ALLOWED_KEY_CODE_PATTERN.test(code)
}

export function shouldSendTextInput(key: string): boolean {
  if (!key || key === 'Dead' || key === 'Process') {
    return false
  }
  if (key.length > 128 || key.length > 1) {
    return false
  }
  const code = key.charCodeAt(0)
  return code >= 32 || code === 9 || code === 10
}
