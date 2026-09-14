/**
 * Meridian Institutional Formatting Engine
 * 
 * Strict honest formatting: NEVER coerce null, undefined, NaN, or non-finite values
 * to healthy zeros ('R$ 0,00' or '0,00%'). Always render explicit 'Indisponível'
 * or 'Não Verificado' when data is missing or errored.
 */

export const isValidNumber = (val) => {
  return typeof val === 'number' && Number.isFinite(val) && !Number.isNaN(val);
};

export const parseNumberSafe = (val) => {
  if (typeof val === 'number') {
    return Number.isFinite(val) ? val : null;
  }
  if (typeof val === 'string') {
    const trimmed = val.trim();
    if (trimmed === '') return null;
    const num = Number(trimmed);
    return Number.isFinite(num) ? num : null;
  }
  return null;
};

/**
 * Format currency to Brazilian Real (BRL).
 * @param {number|null|undefined} value
 * @param {object} options
 * @returns {string}
 */
export const formatCurrency = (value, options = {}) => {
  const {
    fallback = 'Indisponível',
    showSign = false,
    decimals = 2,
  } = options;

  const num = parseNumberSafe(value);
  if (num === null) {
    return fallback;
  }

  // Eliminate negative zero representation (e.g. -0.0000001)
  const effectiveVal = Math.abs(num) < 1e-9 ? 0 : num;

  const formatted = new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Math.abs(effectiveVal));

  if (effectiveVal < 0) {
    return `- ${formatted}`;
  }
  if (showSign && effectiveVal > 0) {
    return `+ ${formatted}`;
  }
  return formatted;
};

/**
 * Format percentage.
 * @param {number|null|undefined} value
 * @param {object} options
 * @returns {string}
 */
export const formatPercent = (value, options = {}) => {
  const {
    fallback = 'Indisponível',
    showSign = true,
    decimals = 2,
    multiplier = 1, // set to 100 if value is fraction (e.g. 0.05 -> 5%)
  } = options;

  const num = parseNumberSafe(value);
  if (num === null) {
    return fallback;
  }

  const calculated = num * multiplier;
  const effectiveVal = Math.abs(calculated) < 1e-9 ? 0 : calculated;

  const formattedNum = new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Math.abs(effectiveVal));

  if (effectiveVal < 0) {
    return `-${formattedNum}%`;
  }
  if (showSign && effectiveVal > 0) {
    return `+${formattedNum}%`;
  }
  return `${formattedNum}%`;
};

/**
 * Format numeric shares / units.
 * @param {number|null|undefined} value
 * @param {object} options
 * @returns {string}
 */
export const formatShares = (value, options = {}) => {
  const {
    fallback = 'Indisponível',
    decimals = 5,
  } = options;

  const num = parseNumberSafe(value);
  if (num === null) {
    return fallback;
  }

  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
};

/**
 * Format standard ratios (Sharpe, Sortino, Calmar, Leverage).
 * @param {number|null|undefined} value
 * @param {object} options
 * @returns {string}
 */
export const formatRatio = (value, options = {}) => {
  const {
    fallback = 'Indisponível',
    decimals = 2,
    suffix = '',
  } = options;

  const num = parseNumberSafe(value);
  if (num === null) {
    return fallback;
  }

  const formatted = new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);

  return `${formatted}${suffix}`;
};

/**
 * Format timestamp / ISO date.
 * @param {string|null|undefined} iso
 * @param {object} options
 * @returns {string}
 */
export const formatDate = (iso, options = {}) => {
  const { fallback = 'Data Não Disponível' } = options;
  if (!iso || typeof iso !== 'string') return fallback;

  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return fallback;
    return d.toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return fallback;
  }
};
