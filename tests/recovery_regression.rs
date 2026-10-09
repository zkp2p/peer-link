use peer_link::recovery::manager::RecoveryManager;
use peer_link::models::{JobStatus, JobError};

#[tokio::test]
async fn test_deferred_terminalization_on_simultaneous_failure() {
    let manager = setup_test_manager().await;
    let job_id = "test_job_123";

    // Simula falha de banco + falha de storage
    let error = JobError::BankFailure(ProviderError::ServiceUnavailable);
    
    let result = manager.handle_critical_failure(job_id, error).await;
    
    assert!(result.is_ok());
    let status = manager.get_job_status(job_id).await.unwrap();
    assert_eq!(status, JobStatus::DeferredTerminalization);
    // Verifica que não houve tentativa de replay de pagamento
    assert_eq!(manager.get_payment_attempts(job_id).await, 0);
}

#[tokio::test]
async fn test_paid_receipt_archival_recovery_trigger() {
    let manager = setup_test_manager().await;
    let job_id = "test_paid_job_456";

    // Configura job como Pago mas com trabalho de arquivamento pendente
    manager.inject_job_state(job_id, JobStatus::Paid, true).await;

    let result = manager.reconcile_restored_job(job_id).await;

    assert!(result.is_ok());
    // Verifica se o trabalho de arquivamento foi processado
    assert!(!manager.get_job_archive_pending(job_id).await);
}
