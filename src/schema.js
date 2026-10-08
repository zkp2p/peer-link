/**
 * Transcript Schema Validation
 * 
 * Provides validation functions for Mercury transcript submissions,
 * ensuring data integrity and protection of sensitive information.
 */

// Valid status values for transcripts
const VALID_STATUSES = ['pending', 'approved', 'rejected'];

// Sensitive data patterns to detect and sanitize
const SENSITIVE_PATTERNS = [
  // Social Security Numbers
  /\b\d{3}-\d{2}-\d{4}\b/g,
  // Bank account numbers (generic)
  /\baccount\s*number[:\s]*\d{10,}/gi,
  // Routing numbers
  /\brouting\s*number[:\s]*\d{9}/gi,
  // IBAN-like patterns
  /\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}\b/g,
  // Credit card numbers
  /\b(?:\d{4}[-\s]?){3}\d{4}\b/g,
  // Private keys / hex sequences (likely sensitive)
  /\b0x[a-fA-F0-9]{64}\b/g,
  // Phone numbers
  /\+\d{11,}/g,
  // Email addresses (for privacy)
  /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g
];

/**
 * Validates a transcript against the Mercury schema
 * @param {Object} transcript - The transcript object to validate
 * @returns {Object} - Validation result with validity flag and errors
 */
function validateTranscriptSchema(transcript) {
  const errors = [];
  
  // Check required fields
  const requiredFields = ['id', 'topic', 'content', 'contributorId'];
  for (const field of requiredFields) {
    if (!transcript[field]) {
      errors.push(`Missing required field: ${field}`);
    }
  }
  
  // Validate topic format (must be non-empty string)
  if (transcript.topic && typeof transcript.topic !== 'string') {
    errors.push('Topic must be a string');
  }
  
  // Validate content format
  if (transcript.content && typeof transcript.content !== 'string') {
    errors.push('Content must be a string');
  }
  
  // Validate contributor ID format
  if (transcript.contributorId) {
    const contributorIdPattern = /^[a-zA-Z0-9_-]{3,50}$/;
    if (!contributorIdPattern.test(transcript.contributorId)) {
      errors.push('Contributor ID must be 3-50 alphanumeric characters, hyphens, or underscores');
    }
  }
  
  // Validate status if provided
  if (transcript.status !== undefined && !VALID_STATUSES.includes(transcript.status)) {
    errors.push(`Status must be one of: ${VALID_STATUSES.join(', ')}`);
  }
  
  // Validate timestamp format if provided
  if (transcript.timestamp) {
    const date = new Date(transcript.timestamp);
    if (isNaN(date.getTime())) {
      errors.push('Invalid timestamp format');
    }
  }
  
  // Check for sensitive data in content
  const hasSensitiveData = SENSITIVE_PATTERNS.some(pattern => pattern.test(transcript.content || ''));
  if (hasSensitiveData) {
    errors.push('Content contains potentially sensitive data');
  }
  
  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Sanitizes transcript content by removing sensitive patterns
 * @param {string} content - The content to sanitize
 * @returns {string} - Sanitized content
 */
function sanitizeContent(content) {
  if (!content) return content;
  
  let sanitized = content;
  for (const pattern of SENSITIVE_PATTERNS) {
    sanitized = sanitized.replace(pattern, '[REDACTED]');
  }
  
  return sanitized;
}

/**
 * Creates a new transcript with default values
 * @param {Object} params - Transcript parameters
 * @returns {Object} - New transcript object
 */
function createTranscript(params) {
  const { topic, content, contributorId } = params;
  
  // Sanitize content before processing
  const sanitizedContent = sanitizeContent(content);
  
  return {
    id: `transcript-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
    topic,
    content: sanitizedContent,
    contributorId,
    timestamp: new Date().toISOString(),
    status: 'pending'
  };
}

module.exports = {
  validateTranscriptSchema,
  sanitizeContent,
  createTranscript,
  VALID_STATUSES,
  SENSITIVE_PATTERNS
};
