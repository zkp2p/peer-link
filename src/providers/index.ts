export { bankOfAmericaProvider } from './bank-of-america'
export { chaseProvider } from './chase'
export { wellsFargoProvider } from './wells-fargo'
export { citiProvider } from './citi'

import { Provider } from '../types/provider'
import { bankOfAmericaProvider } from './bank-of-america'

// Provider registry
export const providers: Record<string, Provider> = {
  'bank-of-america': bankOfAmericaProvider,
  'chase': chaseProvider,
  'wells-fargo': wellsFargoProvider,
  'citi': citiProvider,
}

// Helper to get provider by ID
export function getProvider(id: string): Provider | undefined {
  return providers[id]
}

// Helper to list all providers
export function listProviders(): Provider[] {
  return Object.values(providers)
}
