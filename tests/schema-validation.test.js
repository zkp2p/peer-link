const { validateTranscriptSchema, sanitizeContent } = require('../src/schema');

describe('Transcript Schema Validation', () => {
  describe('validateTranscriptSchema', () => {
    it('should validate a complete transcript', () => {
      const transcript = {
        id: 'transcript-001',
        topic: 'mercury-endpoint-patterns',
        content: 'Discussion about public schema endpoints',
        contributorId: 'user-abc',
        timestamp: new Date().toISOString(),
        status: 'pending'
      };
      
      const result = validateTranscriptSchema(transcript);
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });

    it('should reject incomplete transcripts', () => {
      const incompleteTranscript = {
        topic: 'mercury-endpoint-patterns',
        // Missing required fields
      };
      
      const result = validateTranscriptSchema(incompleteTranscript);
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('should enforce status constraints', () => {
      const transcript = {
        id: 'transcript-002',
        topic: 'test-topic',
        content: 'test content',
        contributorId: 'user-xyz',
        status: 'invalid-status'
      };
      
      const result = validateTranscriptSchema(transcript);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Status must be one of: pending, approved, rejected');
    });
  });

  describe('sanitizeContent', () => {
    it('should remove sensitive patterns from content', () => {
      const content = 'Discussion about schema patterns. My SSN is 123-45-6789 and account is 9876543210.';
      const sanitized = sanitizeContent(content);
      
      expect(sanitized).not.toContain('123-45-6789');
      expect(sanitized).not.toContain('9876543210');
      expect(sanitized).toContain('Discussion about schema patterns');
    });

    it('should preserve legitimate content', () => {
      const content = 'The Mercury transcript schema defines public endpoint patterns for evidence tracking.';
      const sanitized = sanitizeContent(content);
      
      expect(sanitized).toBe(content);
    });
  });
});
