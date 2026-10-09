/**
 * Validate US routing number using Modulus 10 algorithm
 */
export function validateRoutingNumber(routingNumber: string, expectedLength: number = 9): boolean {
  // Check length
  if (routingNumber.length !== expectedLength) {
    return false
  }
  
  // Check all digits
  if (!/^\d+$/.test(routingNumber)) {
    return false
  }
  
  // Modulus 10 validation
  const digits = routingNumber.split('').map(Number)
  const sum = 
    (digits[0] + digits[3] + digits[6]) * 3 +
    (digits[1] + digits[4] + digits[7]) * 1 +
    (digits[2] + digits[5] + digits[8]) * 7
  
  return sum % 10 === 0
}

/**
 * Validate account number format
 */
export function validateAccountNumber(accountNumber: string, minLength: number = 8, maxLength: number = 17): boolean {
  if (accountNumber.length < minLength || accountNumber.length > maxLength) {
    return false
  }
  
  return /^\d+$/.test(accountNumber)
}

/**
 * Validate date format (ISO 8601)
 */
export function validateDateFormat(dateString: string): boolean {
  const date = new Date(dateString)
  return !isNaN(date.getTime()) && dateString.match(/^\d{4}-\d{2}-\d{2}/) !== null
}

/**
 * Validate email format
 */
export function validateEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailRegex.test(email)
}
