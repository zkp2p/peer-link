import { Provider, Transcript, ProofOptions } from '../types/provider'
import { validateRoutingNumber, validateAccountNumber } from '../utils/validation'
import { hashTransactions } from '../utils/cryptography'

export class BankOfAmericaProvider implements Provider {
  readonly id = 'bank-of-america'
  readonly name = 'Bank of America'
  readonly type = 'bank'

  // Bank of America specific configuration
  private static readonly ROUTING_NUMBER_LENGTH = 9
  private static readonly ACCOUNT_NUMBER_MIN = 8
  private static readonly ACCOUNT_NUMBER_MAX = 17
  private static readonly MAX_DATE_RANGE_DAYS = 365
  private static readonly CIRCUIT_ID = 'boa-transcript-proof-v1'

  async validateTranscript(transcript: Transcript): Promise<boolean> {
    // Validate routing number
    if (!validateRoutingNumber(transcript.routingNumber, BankOfAmericaProvider.ROUTING_NUMBER_LENGTH)) {
      return false
    }

    // Validate account number length
    if (
      transcript.accountNumber.length < BankOfAmericaProvider.ACCOUNT_NUMBER_MIN ||
      transcript.accountNumber.length > BankOfAmericaProvider.ACCOUNT_NUMBER_MAX
    ) {
      return false
    }

    // Validate date range
    const startDate = new Date(transcript.startDate)
    const endDate = new Date(transcript.endDate)
    const daysDiff = (endDate.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)
    
    if (daysDiff < 0 || daysDiff > BankOfAmericaProvider.MAX_DATE_RANGE_DAYS) {
      return false
    }

    // Validate transactions exist
    if (!transcript.transactions || transcript.transactions.length === 0) {
      return false
    }

    return true
  }

  async parseStatement(content: string, format: 'csv' | 'ofx' | 'pdf'): Promise<Transcript> {
    switch (format) {
      case 'csv':
        return this.parseCSV(content)
      case 'ofx':
        return this.parseOFX(content)
      case 'pdf':
        throw new Error('PDF parsing requires OCR service - use CSV or OFX format')
      default:
        throw new Error(`Unsupported format: ${format}`)
    }
  }

  private parseCSV(content: string): Transcript {
    const lines = content.trim().split('\n')
    const headers = lines[0].split(',').map(h => h.trim().toLowerCase())
    
    const transactions = lines.slice(1)
      .filter(line => line.trim())
      .map(line => {
        const values = line.split(',')
        const record: Record<string, string> = {}
        headers.forEach((header, index) => {
          record[header] = values[index]?.trim() || ''
        })
        return record
      })

    // Extract date range from transactions
    const dates = transactions
      .map(tx => tx.date || tx['transaction date'])
      .filter(Boolean)
      .sort()

    return {
      provider: this.id,
      routingNumber: '',
      accountNumber: '',
      startDate: dates[0] || new Date().toISOString(),
      endDate: dates[dates.length - 1] || new Date().toISOString(),
      transactions,
      raw: content,
    }
  }

  private parseOFX(content: string): Transcript {
    // Basic OFX parsing - extracts transaction data
    const dateMatches = content.match(/<TRANDATE>([^<]+)<\/TRANDATE>/g) || []
    const amountMatches = content.match(/<TRNAMT>([^<]+)<\/TRNAMT>/g) || []
    const descMatches = content.match(/<NAME>([^<]+)<\/NAME>/g) || []

    const transactions = dateMatches.map((dateMatch, i) => {
      const date = dateMatch.replace(/<TRANDATE>|<\/TRANDATE>/g, '')
      const amount = amountMatches[i]?.replace(/<TRNAMT>|<\/TRNAMT>/g, '') || '0'
      const description = descMatches[i]?.replace(/<NAME>|<\/NAME>/g, '') || ''

      return { date, amount, description }
    })

    const dates = transactions.map(t => t.date).sort()

    return {
      provider: this.id,
      routingNumber: '',
      accountNumber: '',
      startDate: dates[0] || new Date().toISOString(),
      endDate: dates[dates.length - 1] || new Date().toISOString(),
      transactions,
      raw: content,
    }
  }

  async generateProof(transcript: Transcript, options: ProofOptions = {}): Promise<string> {
    // Validate transcript before generating proof
    const isValid = await this.validateTranscript(transcript)
    if (!isValid) {
      throw new Error('Invalid transcript: validation failed')
    }

    // Generate transaction hash for ZKP
    const transactionHash = hashTransactions(transcript.transactions)
    
    // Create proof payload
    const proofPayload = {
      circuitId: BankOfAmericaProvider.CIRCUIT_ID,
      institution: this.id,
      accountId: transcript.accountNumber,
      transactionHash,
      dateRange: {
        start: transcript.startDate,
        end: transcript.endDate,
      },
      timestamp: new Date().toISOString(),
      ...options,
    }

    return JSON.stringify(proofPayload)
  }

  getSupportedFormats(): string[] {
    return ['csv', 'ofx']
  }
}

export const bankOfAmericaProvider = new BankOfAmericaProvider()
