```json
// banks/pk/easypaisa/adapter-easypaisa-pk.js
import { Easypaisa } from '@easypaisa/sdk';

const adapter = {
  manifest: {
    name: 'Easypaisa',
    type: 'bank',
    country: 'Pakistan',
    currency: 'PKR',
    supports: ['easypaisa']
  },
  adapter: async (args) => {
    const { config } = args;
    const { Easypaisa } = config;
    
    const amount = args.transaction.amount;
    const currency = args.transaction.currency;
    const payer = args.transaction.payer;
    const payee = args.transaction.payee;
    
    const transaction = new Easypaisa.Transaction({
      amount: amount,
      currency: currency,
      payer: payer,
      payee: payee
    });
    
    await transaction.send();
    return {
      transactionId: transaction.id,
      status: 'success',
      timestamp: new Date().toISOString()
    };
  }
};

export default adapter;
```