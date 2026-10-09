import { createHash } from 'crypto'

/**
 * Hash transactions for ZKP proof generation
 */
export function hashTransactions(transactions: any[]): string {
  // Sort transactions by date for consistent hashing
  const sorted = [...transactions].sort((a, b) => {
    const dateA = new Date(a.date || a['transaction date'] || 0).getTime()
    const dateB = new Date(b.date || b['transaction date'] || 0).getTime()
    return dateA - dateB
  })
  
  // Create deterministic string representation
  const transactionStrings = sorted.map(tx => {
    const date = tx.date || tx['transaction date'] || ''
    const amount = tx.amount || '0'
    const description = tx.description || tx.memo || ''
    return `${date}|${amount}|${description}`
  }).join(';')
  
  // Generate SHA-256 hash
  return createHash('sha256').update(transactionStrings).digest('hex')
}

/**
 * Generate a unique transaction ID
 */
export function generateTransactionId(transactions: any[]): string {
  const hash = hashTransactions(transactions)
  return hash.substring(0, 16)
}

/**
 * Create a Merkle root from transaction hashes
 */
export function createMerkleRoot(transactions: any[]): string {
  if (transactions.length === 0) {
    return createHash('sha256').update('').digest('hex')
  }
  
  if (transactions.length === 1) {
    return hashTransactions(transactions)
  }
  
  // Build Merkle tree
  let hashes = transactions.map(tx => hashTransactions([tx]))
  
  while (hashes.length > 1) {
    const newLevel: string[] = []
    
    for (let i = 0; i < hashes.length; i += 2) {
      if (i + 1 < hashes.length) {
        // Pair exists, hash together
        const combined = createHash('sha256')
          .update(hashes[i] + hashes[i + 1])
          .digest('hex')
        newLevel.push(combined)
      } else {
        // Odd element, duplicate and hash
        const combined = createHash('sha256')
          .update(hashes[i] + hashes[i])
          .digest('hex')
        newLevel.push(combined)
      }
    }
    
    hashes = newLevel
  }
  
  return hashes[0]
}
