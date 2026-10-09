export interface Transaction {
  date: string
  description: string
  amount: string
  type?: 'credit' | 'debit'
  category?: string
  [key: string]: any
}

export interface Transcript {
  provider: string
  routingNumber: string
  accountNumber: string
  startDate: string
  endDate: string
  transactions: Transaction[]
  raw: string
}

export interface ProofOptions {
  circuitId?: string
  witnessData?: Record<string, any>
  [key: string]: any
}

export interface Provider {
  id: string
  name: string
  type: string
  
  validateTranscript(transcript: Transcript): Promise<boolean>
  parseStatement(content: string, format: string): Promise<Transcript>
  generateProof(transcript: Transcript, options?: ProofOptions): Promise<string>
  getSupportedFormats?(): string[]
}
