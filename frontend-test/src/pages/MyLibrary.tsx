import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import '../styles/MyLibrary.css'

interface BookData { id: string; title: string; author: string; coverImage: string; classNumber: string; status: string; availableCount: number }
interface Reservation { id: string; bookId: string; status: string; dueDate: string; reservedAt: string; userId: string }
interface FavItem { id: string; bookId: string }

function MyLibrary() {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'loans')
  const navigate = useNavigate()
  const [loanItems, setLoanItems] = useState<(Reservation & { book: BookData })[]>([])
  const [favoriteItems, setFavoriteItems] = useState<(FavItem & { book: BookData; displayStatus: string })[]>([])
  const [storageItems, setStorageItems] = useState<(Reservation & { book: BookData })[]>([])
  const [showExtensionModal, setShowExtensionModal] = useState(false)
  const [favBookIds, setFavBookIds] = useState<Set<string>>(new Set())
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const [isProcessing, setIsProcessing] = useState(false)

  useEffect(() => { if (user.id) { fetchLoans(); fetchFavorites(); fetchStorage() } }, [activeTab])

  const fetchLoans = async () => {
    try {
      const res = await fetch(`http://localhost:3001/reservations?userId=${user.id}&status=loaned`)
      const reservations = await res.json()
      const items = await Promise.all(reservations.map(async (r: any) => {
        const bookRes = await fetch(`http://localhost:3001/books/${r.bookId}`)
        const book = await bookRes.json()
        return { ...r, book }
      }))
      setLoanItems(items)
      // favBookIds도 갱신
      const favRes = await fetch(`http://localhost:3001/favorites?userId=${user.id}`)
      const favs = await favRes.json()
      setFavBookIds(new Set(favs.map((f: any) => String(f.bookId))))
    } catch { /* */ }
  }

  const fetchFavorites = async () => {
    try {
      const [resRes, favRes, booksRes] = await Promise.all([
        fetch('http://localhost:3001/reservations'),
        fetch(`http://localhost:3001/favorites?userId=${user.id}`),
        fetch('http://localhost:3001/books')
      ])
      const allReservations = await resRes.json()
      const favs = await favRes.json()
      const allBooks = await booksRes.json()

      // 카운팅 로직
      const borrowCount: Record<string, number> = {}
      const myReservedIds = new Map<string, string>()
      allReservations.forEach((r: any) => {
        if (r.status === 'reserved' || r.status === 'loaned') {
          const bid = String(r.bookId)
          borrowCount[bid] = (borrowCount[bid] || 0) + 1
          if (r.userId === user.id) {
            if (r.status === 'reserved') myReservedIds.set(bid, 'my_reservation')
            else if (r.status === 'loaned') myReservedIds.set(bid, 'my_loan')
          }
        }
      })

      const booksMap: Record<string, BookData> = {}
      allBooks.forEach((b: any) => { booksMap[String(b.id)] = b })

      const items = favs.map((f: any) => {
        const book = booksMap[String(f.bookId)] || { id: f.bookId, title: '알 수 없음', author: '', coverImage: '', classNumber: '', status: 'available', availableCount: 0 }
        const bid = String(f.bookId)
        let displayStatus = 'available'
        if (myReservedIds.has(bid)) displayStatus = myReservedIds.get(bid)!
        else if ((borrowCount[bid] || 0) >= book.availableCount) displayStatus = 'borrowed'
        return { ...f, book, displayStatus }
      })
      setFavoriteItems(items)
      setFavBookIds(new Set(favs.map((f: any) => String(f.bookId))))
    } catch { /* */ }
  }

  const fetchStorage = async () => {
    try {
      const res = await fetch(`http://localhost:3001/reservations?userId=${user.id}&status=reserved`)
      const reservations = await res.json()
      const items = await Promise.all(reservations.map(async (r: any) => {
        const bookRes = await fetch(`http://localhost:3001/books/${r.bookId}`)
        const book = await bookRes.json()
        return { ...r, book }
      }))
      setStorageItems(items)
    } catch { /* */ }
  }

  const handleToggleFavorite = async (bookId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!user.id) return
    if (isProcessing) return
    setIsProcessing(true)
    try {
      const res = await fetch(`http://localhost:3001/favorites?userId=${user.id}`)
      const allFavs = await res.json()
      const targetFavs = allFavs.filter((f: any) => String(f.bookId) === String(bookId))

      if (targetFavs.length > 0) {
        for (const fav of targetFavs) {
          await fetch(`http://localhost:3001/favorites/${fav.id}`, { method: 'DELETE' })
        }
      } else {
        await fetch('http://localhost:3001/favorites', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId: user.id, bookId: String(bookId) })
        })
      }
      fetchFavorites()
      fetchLoans() // 대출 탭 갱신용
    } catch { /* */ } finally { setIsProcessing(false) }
  }

  const handleReturn = async (reservationId: string) => {
    if (isProcessing) return
    setIsProcessing(true)
    try {
      await fetch(`http://localhost:3001/reservations/${reservationId}`, { method: 'DELETE' })
      fetchLoans(); fetchFavorites()
    } catch { alert('오류가 발생했습니다.') } finally { setIsProcessing(false) }
  }

  const handleOpenLocker = async (item: Reservation & { book: BookData }) => {
    if (isProcessing) return
    setIsProcessing(true)
    try {
      const dueDate = new Date()
      dueDate.setDate(dueDate.getDate() + 14)
      await fetch(`http://localhost:3001/reservations/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: item.userId, bookId: item.bookId, status: 'loaned', dueDate: dueDate.toISOString(), reservedAt: item.reservedAt })
      })
      fetchLoans(); fetchStorage(); fetchFavorites()
    } catch { alert('오류가 발생했습니다.') } finally { setIsProcessing(false) }
  }

  const getDday = (d: string) => { const diff = Math.ceil((new Date(d).getTime() - Date.now()) / 86400000); return `D-${Math.max(0, diff)}` }
  const formatDate = (d: string) => { const dt = new Date(d); return `${dt.getFullYear()}.${String(dt.getMonth() + 1).padStart(2, '0')}.${String(dt.getDate()).padStart(2, '0')}` }
  const getPickupDeadline = (d: string) => { const dt = new Date(d); dt.setHours(dt.getHours() + 1); return `${dt.getHours()}:${String(dt.getMinutes()).padStart(2, '0')}` }
  const isOverdue = (d: string) => Math.ceil((new Date(d).getTime() - Date.now()) / 86400000) <= 3

  return (
    <div className="page-container">
      <div className="top-nav"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg><span className="logo-text">XYZ 도서관</span></div>
      <div className="mylibrary-content">
        <h1 className="mylibrary-title">내 서재</h1>
        <div className="tab-group">
          <button className={`tab-btn ${activeTab === 'loans' ? 'active' : ''}`} onClick={() => setActiveTab('loans')}>대출현황</button>
          <button className={`tab-btn ${activeTab === 'favorites' ? 'active' : ''}`} onClick={() => setActiveTab('favorites')}>관심도서</button>
          <button className={`tab-btn ${activeTab === 'storage' ? 'active' : ''}`} onClick={() => setActiveTab('storage')}>보관도서</button>
        </div>

        {activeTab === 'loans' && (<div className="tab-content">
          <div className="section-count"><span className="section-count-title">총 {loanItems.length}권 대출 중</span></div>
          {loanItems.length === 0 ? <div className="tab-content-empty">대출한 책이 없습니다.</div> : (
            <div className="book-list">{loanItems.map(item => (<div className="book-card" key={item.id}>
              <div className="book-card-cover" onClick={() => navigate(`/book/${item.bookId}`)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div>
              <div className="book-card-info">
                <div className="book-card-title-row"><div className="book-card-title">{item.book.title}</div>
                  <div className="book-card-actions">
                    <button className="book-card-fav-btn" onClick={(e) => handleToggleFavorite(String(item.bookId), e)}><svg viewBox="0 0 24 24" fill={favBookIds.has(String(item.bookId)) ? '#E03131' : 'none'} stroke={favBookIds.has(String(item.bookId)) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg></button>
                    <button className="book-card-return-btn" onClick={() => handleReturn(item.id)}>반납하기</button>
                  </div>
                </div>
                <div className="book-card-meta">{item.book.classNumber}</div>
                <div className="book-card-meta">{item.book.author} 지음</div>
                <div className="book-card-due-row"><span className={`book-card-due ${isOverdue(item.dueDate) ? 'overdue' : ''}`}>반납일: {formatDate(item.dueDate)}</span><button className="book-card-extend-btn" onClick={() => setShowExtensionModal(true)}>연장하기</button></div>
              </div>
            </div>))}</div>
          )}
        </div>)}

        {activeTab === 'favorites' && (<div className="tab-content">
          <div className="section-count"><span className="section-count-title">총 {favoriteItems.length}권의 관심도서</span></div>
          {favoriteItems.length === 0 ? <div className="tab-content-empty">관심도서가 없습니다.</div> : (
            <div className="book-list">{favoriteItems.map(item => (<div className="book-card" key={item.id}>
              <div className="book-card-cover" onClick={() => navigate(`/book/${item.book.id}`)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div>
              <div className="book-card-info">
                <div className="book-card-title-row"><div className="book-card-title">{item.book.title}</div>
                  <button className="book-card-fav-btn" onClick={(e) => handleToggleFavorite(String(item.bookId), e)}><svg viewBox="0 0 24 24" fill={favBookIds.has(String(item.bookId)) ? '#E03131' : 'none'} stroke={favBookIds.has(String(item.bookId)) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg></button>
                </div>
                <div className="book-card-meta">{item.book.classNumber}</div>
                <div className="book-card-meta">{item.book.author} 지음</div>
                <div className="book-card-bottom-row">
                  {item.displayStatus === 'available' && (<><span className="badge-available">대출가능</span><button className="book-card-reserve-btn" onClick={() => navigate(`/book/${item.book.id}`)}>예약하기</button></>)}
                  {(item.displayStatus === 'borrowed' || item.displayStatus === 'my_loan') && (<><span className="badge-unavailable">대출불가</span><button className="book-card-reserve-btn disabled" disabled>예약불가</button></>)}
                  {item.displayStatus === 'my_reservation' && (<><span className="badge-myreserve">예약완료</span><button className="book-card-reserve-btn disabled" disabled>예약완료</button></>)}
                </div>
              </div>
            </div>))}</div>
          )}
        </div>)}

        {activeTab === 'storage' && (<div className="tab-content">
          <div className="section-count"><span className="section-count-title">보관 중인 도서</span><span className="section-count-number">현재 {storageItems.length}권 보관중</span></div>
          {storageItems.length > 0 && (<div className="info-banner"><div className="info-banner-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" /></svg></div><span className="info-banner-text">수령 기한이 지나면 도서가 자동으로 반납됩니다.</span></div>)}
          {storageItems.length === 0 ? <div className="tab-content-empty">보관 중인 도서가 없습니다.</div> : (
            <div className="book-list">{storageItems.map(item => (<div className="book-card" key={item.id}>
              <div className="book-card-cover" onClick={() => navigate(`/book/${item.bookId}`)}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div>
              <div className="book-card-info">
                <div className="book-card-title-row"><div className="book-card-title">{item.book.title}</div>
                  <button className="book-card-fav-btn" onClick={(e) => handleToggleFavorite(String(item.bookId), e)}><svg viewBox="0 0 24 24" fill={favBookIds.has(String(item.bookId)) ? '#E03131' : 'none'} stroke={favBookIds.has(String(item.bookId)) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg></button>
                </div>
                <div className="book-card-meta">{item.book.classNumber}</div>
                <div className="book-card-meta">{item.book.author} 지음</div>
                <div className="book-card-storage-badge"><span className="badge-storage">수령 대기</span></div>
                <div className="book-card-storage-info">
                  <div className="book-card-storage-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg><span>보관 장소: 무인 보관함 {item.id}번</span></div>
                  <button className="book-card-locker-btn" onClick={() => handleOpenLocker(item)}>보관함 열기</button>
                  <div className="book-card-storage-row deadline"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg><span>수령 기한: 금일 {getPickupDeadline(item.reservedAt)} 까지</span></div>
                </div>
              </div>
            </div>))}</div>
          )}
        </div>)}
      </div>
      {showExtensionModal && (<div className="mypage-modal-overlay" onClick={() => setShowExtensionModal(false)}><div className="mypage-modal" onClick={(e) => e.stopPropagation()}><p className="mypage-modal-text">현재 지원하지 않는 기능입니다.</p><button className="mypage-modal-btn" onClick={() => setShowExtensionModal(false)}>확인</button></div></div>)}
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item active" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}
export default MyLibrary
