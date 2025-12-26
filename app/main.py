from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app.db import init_db, close_db
from app.api.routers import auth, businesses, customers, services, staff, appointments, transactions, settings, dashboard, booking_links, public_booking, users
from app.dependencies import get_current_user_for_html, require_owner_or_admin, require_owner, require_not_staff

app = FastAPI(
    title="Appointment Booking System API",
    description="""
    Multi-tenant online appointment booking system.
    
    ## Features
    - JWT Authentication
    - Multi-tenant (Business-based)
    - Double-booking prevention
    - Complex queries and reports
    - Real-time availability calculation
    - Transaction management with idempotency
    
    ## Authentication
    All endpoints (except `/api/auth/register` and `/api/auth/login`) require JWT authentication.
    Include the token in the Authorization header: `Bearer <token>`
    
    ## Multi-tenancy
    All data is automatically filtered by the authenticated user's business_id.
    """,
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jinja2 Templates yapılandırması
templates = Jinja2Templates(directory="app/templates")

# Static dosyalar için mount
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.on_event("startup")
async def startup():
    await init_db()

@app.on_event("shutdown")
async def shutdown():
    await close_db()

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "API is running"}

# Template route'ları
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Ana dashboard sayfası"""
    return templates.TemplateResponse("dashboard/index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login sayfası"""
    return templates.TemplateResponse("auth/login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Register sayfası"""
    return templates.TemplateResponse("auth/register.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Dashboard sayfası (login sonrası yönlendirme)"""
    return templates.TemplateResponse("dashboard/index.html", {"request": request})

@app.get("/appointments/calendar", response_class=HTMLResponse)
async def appointments_calendar(request: Request):
    """Appointment calendar sayfası"""
    return templates.TemplateResponse("appointments/calendar.html", {"request": request})

@app.get("/customers", response_class=HTMLResponse)
async def customers_list(request: Request):
    """Customer list sayfası"""
    return templates.TemplateResponse("customers/list.html", {"request": request})

@app.get("/customers/create", response_class=HTMLResponse)
async def customers_create(request: Request):
    """Create customer sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot create
    return templates.TemplateResponse("customers/create.html", {"request": request})

@app.get("/customers/{customer_id}/edit", response_class=HTMLResponse)
async def customers_edit(request: Request, customer_id: int):
    """Customer edit sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot edit
    return templates.TemplateResponse("customers/edit.html", {"request": request, "customer_id": customer_id})

@app.get("/customers/{customer_id}", response_class=HTMLResponse)
async def customers_view(request: Request, customer_id: int):
    """Customer view sayfası"""
    return templates.TemplateResponse("customers/view.html", {"request": request, "customer_id": customer_id})

@app.get("/services", response_class=HTMLResponse)
async def services_list(request: Request):
    """Services list sayfası"""
    return templates.TemplateResponse("services/list.html", {"request": request})

@app.get("/services/create", response_class=HTMLResponse)
async def services_create(request: Request):
    """Create service sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot create
    return templates.TemplateResponse("services/create.html", {"request": request})

@app.get("/services/{service_id}/edit", response_class=HTMLResponse)
async def services_edit(request: Request, service_id: int):
    """Service edit sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot edit
    return templates.TemplateResponse("services/edit.html", {"request": request, "service_id": service_id})

@app.get("/services/top-selling", response_class=HTMLResponse)
async def services_top_selling(request: Request):
    """Top selling services report sayfası"""
    return templates.TemplateResponse("services/top-selling.html", {"request": request})

@app.get("/staff", response_class=HTMLResponse)
async def staff_list(request: Request):
    """Staff list sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot access
    return templates.TemplateResponse("staff/list.html", {"request": request})

@app.get("/staff/create", response_class=HTMLResponse)
async def staff_create(request: Request):
    """Create staff sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot access
    return templates.TemplateResponse("staff/create.html", {"request": request})

@app.get("/staff/{staff_id}/edit", response_class=HTMLResponse)
async def staff_edit(request: Request, staff_id: int):
    """Staff edit sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot access
    return templates.TemplateResponse("staff/edit.html", {"request": request, "staff_id": staff_id})

@app.get("/404", response_class=HTMLResponse)
async def error_404(request: Request):
    """404 error sayfası"""
    return templates.TemplateResponse("errors/404.html", {"request": request})

@app.get("/logout", response_class=HTMLResponse)
async def logout_page(request: Request):
    """Logout sayfası"""
    return templates.TemplateResponse("auth/logout.html", {"request": request})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Business settings sayfası - staff role cannot access"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    require_not_staff(user)  # Staff cannot access
    return templates.TemplateResponse("settings/business.html", {"request": request})

@app.get("/appointments", response_class=HTMLResponse)
async def appointments_list(request: Request):
    """Appointments list sayfası"""
    return templates.TemplateResponse("appointments/list.html", {"request": request})

@app.get("/appointments/create", response_class=HTMLResponse)
async def appointments_create(request: Request):
    """Create appointment sayfası"""
    return templates.TemplateResponse("appointments/create.html", {"request": request})

@app.get("/appointments/{appointment_id}", response_class=HTMLResponse)
async def appointments_view(request: Request, appointment_id: int):
    """Appointment view sayfası"""
    user = await get_current_user_for_html(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    
    # Staff kontrolü - staff sadece kendi appointmentlarını görebilir
    if user.get("role") == "staff":
        user_staff_id = user.get("staff_id")
        if user_staff_id is None:
            return RedirectResponse(url="/dashboard", status_code=302)
        
        # Appointment'ın staff_id'sini kontrol et
        from app.db import get_db
        import aiomysql
        db_pool = await get_db()
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT staff_id FROM appointments WHERE id = %s AND business_id = %s LIMIT 1",
                    (appointment_id, user.get("business_id"))
                )
                appointment = await cursor.fetchone()
                if not appointment or appointment.get("staff_id") != user_staff_id:
                    return RedirectResponse(url="/dashboard", status_code=302)
    
    return templates.TemplateResponse("appointments/view.html", {"request": request, "appointment_id": appointment_id})

@app.get("/appointments/{appointment_id}/edit", response_class=HTMLResponse)
async def appointments_edit(request: Request, appointment_id: int):
	"""Appointment edit sayfası"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	
	# Staff kontrolü - staff sadece kendi appointmentlarını düzenleyebilir
	if user.get("role") == "staff":
		user_staff_id = user.get("staff_id")
		if user_staff_id is None:
			return RedirectResponse(url="/dashboard", status_code=302)
		
		# Appointment'ın staff_id'sini kontrol et
		from app.db import get_db
		import aiomysql
		db_pool = await get_db()
		async with db_pool.acquire() as conn:
			async with conn.cursor(aiomysql.DictCursor) as cursor:
				await cursor.execute(
					"SELECT staff_id FROM appointments WHERE id = %s AND business_id = %s LIMIT 1",
					(appointment_id, user.get("business_id"))
				)
				appointment = await cursor.fetchone()
				if not appointment or appointment.get("staff_id") != user_staff_id:
					return RedirectResponse(url="/dashboard", status_code=302)
	
	return templates.TemplateResponse("appointments/edit.html", {"request": request, "appointment_id": appointment_id})

@app.get("/booking-links/create", response_class=HTMLResponse)
async def booking_links_create(request: Request):
	"""Create booking link sayfası - staff role cannot access"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	require_not_staff(user)  # Staff cannot access
	return templates.TemplateResponse("booking/links/create.html", {"request": request})

@app.get("/booking-links", response_class=HTMLResponse)
async def booking_links_list(request: Request):
	"""Booking links list sayfası - staff role cannot access"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	require_not_staff(user)  # Staff cannot access
	return templates.TemplateResponse("booking/links/list.html", {"request": request})

@app.get("/booking-links/{booking_link_id}/edit", response_class=HTMLResponse)
async def booking_links_edit(request: Request, booking_link_id: int):
	"""Edit booking link sayfası - staff role cannot access"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	require_not_staff(user)  # Staff cannot access
	return templates.TemplateResponse("booking/links/edit.html", {"request": request, "booking_link_id": booking_link_id})

@app.get("/appointment-requests", response_class=HTMLResponse)
async def appointment_requests_list(request: Request):
	"""Appointment requests list sayfası - staff role cannot access"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	require_not_staff(user)  # Staff cannot access
	return templates.TemplateResponse("booking/requests/list.html", {"request": request})

@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request):
	"""Users list sayfası - only owner can access"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	require_owner(user)  # Only owner can access
	return templates.TemplateResponse("users/list.html", {"request": request})

@app.get("/users/create", response_class=HTMLResponse)
async def users_create(request: Request):
	"""Create user sayfası - only owner can access"""
	user = await get_current_user_for_html(request)
	if user is None:
		return RedirectResponse(url="/login", status_code=302)
	require_owner(user)  # Only owner can access
	return templates.TemplateResponse("users/create.html", {"request": request})

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
	"""Reset password sayfası"""
	return templates.TemplateResponse("auth/reset-password.html", {"request": request})

@app.get("/new-password", response_class=HTMLResponse)
async def new_password_page(request: Request):
	"""New password sayfası"""
	return templates.TemplateResponse("auth/new-password.html", {"request": request})

# Router'ları ekle
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(businesses.router, prefix="/api/businesses", tags=["businesses"])
app.include_router(customers.router, prefix="/api/customers", tags=["customers"])
app.include_router(services.router, prefix="/api/services", tags=["services"])
app.include_router(staff.router, prefix="/api/staff", tags=["staff"])
app.include_router(appointments.router, prefix="/api/appointments", tags=["appointments"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["transactions"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(booking_links.router, prefix="/api/booking-links", tags=["booking-links"])
app.include_router(public_booking.router, prefix="", tags=["public-booking"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
