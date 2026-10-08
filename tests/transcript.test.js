const app = require('../src/index.js');
const request = require('supertest');

describe('Transcript API', () => {
  describe('GET /api/transcripts', () => {
    it('should return transcripts endpoint', async () => {
      const res = await request(app).get('/api/transcripts');
      expect(res.status).toBe(200);
      expect(res.body).toHaveProperty('transcripts');
      expect(res.body).toHaveProperty('message');
    });
  });

  describe('POST /api/transcripts', () => {
    it('should reject submission without required fields', async () => {
      const res = await request(app).post('/api/transcripts').send({});
      expect(res.status).toBe(400);
    });

    it('should accept valid transcript submission', async () => {
      const validTranscript = {
        topic: 'mercury-schema-v1',
        content: 'Public schema discussion for endpoint patterns',
        contributorId: 'contributor-123'
      };
      
      const res = await request(app).post('/api/transcripts').send(validTranscript);
      expect(res.status).toBe(200);
      expect(res.body).toHaveProperty('success', true);
    });

    it('should reject submission with sensitive data', async () => {
      const invalidTranscript = {
        topic: 'test-topic',
        content: 'My bank account number is 1234567890 and routing number is 987654321',
        contributorId: 'contributor-123'
      };
      
      const res = await request(app).post('/api/transcripts').send(invalidTranscript);
      expect(res.status).toBe(400);
      expect(res.body.error).toContain('sensitive data');
    });
  });

  describe('GET /health', () => {
    it('should return health status', async () => {
      const res = await request(app).get('/health');
      expect(res.status).toBe(200);
      expect(res.body).toEqual({ status: 'ok', service: 'peer-link' });
    });
  });
});
