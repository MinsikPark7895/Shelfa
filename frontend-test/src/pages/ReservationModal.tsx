import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

interface ReservationModalProps {
  bookId: number
  title: string
  author: string
  classNumber: string
  badgeLabel: string
  badgeClass: string
  onClose: () => void
  onSuccess?: () => void
}

type ModalStep = 'confirm' | 'success' | 'fail'

function ReservationModal({ bookId, title, author, classNumber, badgeLabel, badgeClass, onClose, onSuccess }: ReservationModalProps) {
  const navigate = useNavigate()
  const [step, setStep] = useState<ModalStep>('confirm')
  const [failReason, setFailReason] = useState('')

  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const maxBorrow = user.maxBorrow || 5

  const getDueDate = () => {
    const date = new Date()
    date.setDate(date.getDate() + 14)
    return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일`
  }

  const handleConfirm = async () => {
    try {
      // 대출 한도 체크
      const loansRes = await fetch(`http://localhost:3001/reservations?userId=${user.id}&status=loaned`)
      const loans = await loansRes.json()
      const reservedRes = await fetch(`http://localhost:3001/reservations?userId=${user.id}&status=reserved`)
      const reserved = await reservedRes.json()
      const totalCount = loans.length + reserved.length

      if (totalCount >= maxBorrow) {
        setFailReason('대출 가능한 도서를 모두 대출했습니다.')
        setStep('fail')
        return
      }

      // 중복 예약 체크
      const dupRes = await fetch(`http://localhost:3001/reservations?userId=${user.id}&bookId=${bookId}`)
      const dups = await dupRes.json()
      const activeDup = dups.find((r: any) => r.status === 'reserved' || r.status === 'loaned')
      if (activeDup) {
        setFailReason('이미 예약 또는 대출 중인 책입니다.')
        setStep('fail')
        return
      }

      const dueDate = new Date()
      dueDate.setDate(dueDate.getDate() + 14)
      const res = await fetch('http://localhost:3001/reservations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: user.id, bookId, status: 'reserved', reservedAt: new Date().toISOString(), dueDate: dueDate.toISOString() })
      })

      if (res.ok) {
        setStep('success')
        if (onSuccess) onSuccess()
      } else {
        setFailReason('일시적인 오류가 발생했습니다.')
        setStep('fail')
      }
    } catch {
      setFailReason('서버 연결에 실패했습니다.')
      setStep('fail')
    }
  }

  return (
    <div className="modal-overlay" onClick={step === 'confirm' ? onClose : undefined}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>

        {step === 'confirm' && (
          <>
            <div className="modal-book-info">
              <span className={`bookdetail-badge ${badgeClass}`}>{badgeLabel}</span>
              <h3 className="modal-book-title">{title}</h3>
              <p className="modal-book-class">{classNumber}</p>
              <p className="modal-book-author">{author} 지음</p>
            </div>
            <div className="modal-loan-info">
              <p className="modal-loan-available">현재 {maxBorrow}권까지 대출 가능합니다.</p>
              <p className="modal-loan-due">• {getDueDate()}까지 대출 가능합니다.</p>
            </div>
            <button className="modal-reserve-btn" onClick={handleConfirm}>예약하기</button>
          </>
        )}

        {step === 'success' && (
          <div className="modal-result">
            <div className="modal-result-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="#4CAF50" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><polyline points="9 12 11.5 14.5 16 9.5" />
              </svg>
            </div>
            <p className="modal-result-text">예약이 완료되었습니다.</p>
            <div className="modal-result-buttons">
              <button className="modal-btn-outline" onClick={() => { onClose(); navigate('/search') }}>계속 예약하기</button>
              <button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button>
            </div>
          </div>
        )}

        {step === 'fail' && (
          <div className="modal-result">
            <div className="modal-result-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="#E03131" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <p className="modal-result-text">예약에 실패하였습니다.</p>
            <p className="modal-fail-reason">{failReason}</p>
            <div className="modal-result-buttons">
              <button className="modal-btn-outline" onClick={onClose}>상세페이지로</button>
              <button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

export default ReservationModal
