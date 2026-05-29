import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import '../styles/BookDetail.css'

type ModalType = 'none' | 'confirm' | 'success' | 'fail'

interface BookData {
  id: string; title: string; author: string; translator?: string; publisher: string
  classNumber: string; coverImage: string; status: string; availableCount: number; synopsis: string
}

function BookDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [book, setBook] = useState<BookData | null>(null)
  const [displayStatus, setDisplayStatus] = useState('available')
  const [isFavorite, setIsFavorite] = useState(false)
  const [modalType, setModalType] = useState<ModalType>('none')
  const [failReason, setFailReason] = useState('')
  const [remainingBorrow, setRemainingBorrow] = useState(5)
  const [isProcessing, setIsProcessing] = useState(false)

  const user = JSON.parse(localStorage.getItem('user') || '{}')

  useEffect(() => { fetchBook(); checkFavorite(); checkStatus() }, [id])

  const fetchBook = async () => {
    try {
      const res = await fetch(`http://localhost:3001/books/${id}`)
      setBook(await res.json())
    } catch { /* */ }
  }

  const checkFavorite = async () => {
    if (!user.id) return
    try {
      const res = await fetch(`http://localhost:3001/favorites?userId=${user.id}`)
      const allFavs = await res.json()
      // 문자열로 완벽히 필터링
      setIsFavorite(allFavs.some((f: any) => String(f.bookId) === String(id)))
    } catch { /* */ }
  }

  const checkStatus = async () => {
    try {
      const [bookRes, allResRes] = await Promise.all([
        fetch(`http://localhost:3001/books/${id}`),
        fetch('http://localhost:3001/reservations')
      ])
      const bookData = await bookRes.json()
      const allReservations = await allResRes.json()

      // 이 책에 대한 예약/대출만 필터 (String 비교)
      const bookReservations = allReservations.filter((r: any) => String(r.bookId) === String(id) && (r.status === 'reserved' || r.status === 'loaned'))
      const activeCount = bookReservations.length
      const myActive = user.id ? bookReservations.find((r: any) => r.userId === user.id) : null

      if (myActive) {
        setDisplayStatus(myActive.status === 'loaned' ? 'my_loan' : 'my_reservation')
      } else if (activeCount >= bookData.availableCount) {
        setDisplayStatus('borrowed')
      } else {
        setDisplayStatus('available')
      }

      // 남은 대출 가능 권수
      if (user.id) {
        const myActiveCount = allReservations.filter((r: any) => r.userId === user.id && (r.status === 'reserved' || r.status === 'loaned')).length
        setRemainingBorrow((user.maxBorrow || 5) - myActiveCount)
      }
    } catch { /* */ }
  }

  const getDueDate = () => {
    const date = new Date(); date.setDate(date.getDate() + 14)
    return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일`
  }

  const handleReservationClick = () => {
    if (!user.id) { alert('로그인이 필요합니다.'); navigate('/login'); return }
    if (remainingBorrow <= 0) { setFailReason('대출 가능한 도서를 모두 대출했습니다.'); setModalType('fail'); return }
    setModalType('confirm')
  }

  const handleReservationConfirm = async () => {
    if (isProcessing) return
    setIsProcessing(true)
    try {
      // 중복 예약 체크
      const dupRes = await fetch(`http://localhost:3001/reservations?userId=${user.id}&bookId=${id}`)
      const dups = await dupRes.json()
      if (dups.some((r: any) => r.status === 'reserved' || r.status === 'loaned')) {
        setFailReason('이미 예약 또는 대출 중인 책입니다.'); setModalType('fail'); return
      }
      if (remainingBorrow <= 0) { setFailReason('대출 한도를 초과했습니다.'); setModalType('fail'); return }

      const dueDate = new Date(); dueDate.setDate(dueDate.getDate() + 14)
      const res = await fetch('http://localhost:3001/reservations', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: user.id, bookId: String(id), status: 'reserved', reservedAt: new Date().toISOString(), dueDate: dueDate.toISOString() })
      })
      if (res.ok) { setModalType('success'); setDisplayStatus('my_reservation') }
      else { setFailReason('일시적인 오류가 발생했습니다.'); setModalType('fail') }
    } catch { setFailReason('서버 연결에 실패했습니다.'); setModalType('fail') } finally { setIsProcessing(false) }
  }

  const handleFavoriteToggle = async () => {
    if (!user.id) { alert('로그인이 필요합니다.'); navigate('/login'); return }
    if (isProcessing) return
    setIsProcessing(true)
    try {
      const res = await fetch(`http://localhost:3001/favorites?userId=${user.id}`)
      const allFavs = await res.json()
      const targetFavs = allFavs.filter((f: any) => String(f.bookId) === String(id))

      if (targetFavs.length > 0) {
        // Promise.all 대신 안전한 순차 삭제 적용
        for (const fav of targetFavs) {
          await fetch(`http://localhost:3001/favorites/${fav.id}`, { method: 'DELETE' })
        }
        setIsFavorite(false)
      } else {
        await fetch('http://localhost:3001/favorites', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId: user.id, bookId: String(id) })
        })
        setIsFavorite(true)
      }
    } catch { /* */ } finally { setIsProcessing(false) }
  }

  if (!book) return <div className="page-container"><div className="top-nav"><span className="logo-text">로딩중...</span></div></div>

  const statusConfig: Record<string, any> = {
    available: { label: '대출가능', badgeClass: 'badge-available', buttonText: '예약하기', buttonDisabled: false },
    borrowed: { label: '대출불가', badgeClass: 'badge-unavailable', buttonText: '예약불가', buttonDisabled: true },
    my_loan: { label: '대출중', badgeClass: 'badge-myloan', buttonText: '이미 대출한 책입니다', buttonDisabled: true },
    my_reservation: { label: '예약완료', badgeClass: 'badge-myreserve', buttonText: '이미 예약한 책입니다', buttonDisabled: true },
  }
  const sc = statusConfig[displayStatus] || statusConfig.available

  return (
    <div className="page-container">
      <div className="top-nav"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg><span className="logo-text">XYZ 도서관</span></div>
      <div className="bookdetail-content">
        <div className="bookdetail-header"><h1 className="bookdetail-title">도서상세</h1>
          <button className="bookdetail-favorite-btn" onClick={handleFavoriteToggle}>
            <svg viewBox="0 0 24 24" fill={isFavorite ? 'var(--navy)' : 'none'} stroke="var(--navy)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg>
          </button>
        </div>
        <div className="bookdetail-cover-section"><div className="bookdetail-cover"><div className="bookdetail-cover-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div></div></div>
        <div className="bookdetail-badge-row"><span className={`bookdetail-badge ${sc.badgeClass}`}>{sc.label}</span></div>
        <div className="bookdetail-info">
          <h2 className="bookdetail-book-title">{book.title}</h2>
          <p className="bookdetail-meta">{book.author} 저자{book.translator && <> {book.translator} 번역</>}</p>
          <p className="bookdetail-publisher">{book.publisher}</p>
          <p className="bookdetail-class-number">{book.classNumber}</p>
        </div>
        <div className="bookdetail-action"><button className={`bookdetail-reserve-btn ${sc.buttonDisabled ? 'disabled' : ''}`} onClick={handleReservationClick} disabled={sc.buttonDisabled}>{sc.buttonText}</button></div>
        <div className="bookdetail-synopsis"><h3 className="bookdetail-synopsis-title">줄거리</h3><p className="bookdetail-synopsis-subtitle">{book.synopsis.split('\n')[0]}</p><p className="bookdetail-synopsis-text">{book.synopsis.split('\n').slice(1).join('\n')}</p></div>
      </div>
      {modalType === 'confirm' && (<div className="modal-overlay" onClick={() => setModalType('none')}><div className="modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-book-info"><span className={`bookdetail-badge ${sc.badgeClass}`}>{sc.label}</span><h3 className="modal-book-title">{book.title}</h3><p className="modal-book-class">{book.classNumber}</p><p className="modal-book-author">{book.author} 지음</p></div>
        <div className="modal-loan-info"><p className="modal-loan-available">현재 {remainingBorrow}권 대출 가능합니다.</p><p className="modal-loan-due">• {getDueDate()}까지 대출 가능합니다.</p></div>
        <button className="modal-reserve-btn" onClick={handleReservationConfirm}>예약하기</button>
      </div></div>)}
      {modalType === 'success' && (<div className="modal-overlay"><div className="modal-content modal-result">
        <div className="modal-result-icon"><svg viewBox="0 0 24 24" fill="none" stroke="#4CAF50" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="9 12 11.5 14.5 16 9.5" /></svg></div>
        <p className="modal-result-text">예약이 완료되었습니다.</p>
        <div className="modal-result-buttons"><button className="modal-btn-outline" onClick={() => { setModalType('none'); navigate('/search') }}>계속 예약하기</button><button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button></div>
      </div></div>)}
      {modalType === 'fail' && (<div className="modal-overlay"><div className="modal-content modal-result">
        <div className="modal-result-icon"><svg viewBox="0 0 24 24" fill="none" stroke="#E03131" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg></div>
        <p className="modal-result-text">예약에 실패하였습니다.</p><p className="modal-fail-reason">{failReason}</p>
        <div className="modal-result-buttons"><button className="modal-btn-outline" onClick={() => setModalType('none')}>상세페이지로</button><button className="modal-btn-outline" onClick={() => navigate('/my-library')}>내 서재로</button></div>
      </div></div>)}
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item active" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}
export default BookDetail
