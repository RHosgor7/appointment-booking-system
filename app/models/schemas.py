from pydantic import BaseModel, EmailStr, ConfigDict, model_serializer
from typing import Optional, List, Literal, Any
from decimal import Decimal
from datetime import datetime, time

# Base Response Model (Decimal JSON encoder ile - recursive)
class BaseResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def _serialize_decimal_recursive(obj):
        """Recursive Decimal serialization helper"""
        if isinstance(obj, Decimal):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: BaseResponseModel._serialize_decimal_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [BaseResponseModel._serialize_decimal_recursive(item) for item in obj]
        else:
            return obj

    @model_serializer(mode='wrap')
    def serialize_model(self, serializer, info):
        data = serializer(self)
        # Decimal alanlarını recursive olarak string'e çevir
        return BaseResponseModel._serialize_decimal_recursive(data)

# Auth
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    business_name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    id: int
    business_id: int
    email: str
    full_name: str
    role: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetResponse(BaseModel):
    message: str

class NewPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    password: str
    confirm_password: str

# Users Management
class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: Literal["admin", "staff"]  # Owner cannot be created via UI
    link_to_staff_id: Optional[int] = None  # Optional: Link to existing staff profile

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[Literal["admin", "staff"]] = None

class UserListResponse(BaseResponseModel):
    id: int
    business_id: int
    email: str
    full_name: str
    role: str
    created_at: datetime
    updated_at: datetime
    has_staff_profile: bool  # Computed: staff.id IS NOT NULL
    staff_id: Optional[int] = None  # If linked to staff

# Business
class BusinessCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    address: Optional[str] = None

class BusinessResponse(BaseResponseModel):
    id: int
    name: str
    email: EmailStr
    phone: Optional[str]
    address: Optional[str]
    created_at: datetime
    updated_at: datetime

# Customer
class CustomerCreate(BaseModel):
    email: EmailStr
    phone: Optional[str] = None
    full_name: str

class CustomerUpdate(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None

class CustomerResponse(BaseResponseModel):
    id: int
    business_id: int
    email: EmailStr
    phone: Optional[str]
    full_name: str
    created_at: datetime
    updated_at: datetime

# Service
class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    duration_minutes: int
    price: Decimal
    is_active: bool = True

class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    price: Optional[Decimal] = None
    is_active: Optional[bool] = None

class ServiceResponse(BaseResponseModel):
    id: int
    business_id: int
    name: str
    description: Optional[str]
    duration_minutes: int
    price: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

# Staff
class StaffCreate(BaseModel):
    full_name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    is_active: bool = True
    panel_access: bool = False  # Panel Access toggle
    role: Optional[Literal["admin", "staff"]] = None  # Role (only if panel_access is True)
    password: Optional[str] = None  # Password (only if panel_access is True)

class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None

class StaffResponse(BaseResponseModel):
    id: int
    business_id: int
    user_id: Optional[int]
    full_name: str
    email: Optional[EmailStr]
    phone: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

# Appointment
from pydantic import conlist

class AppointmentCreate(BaseModel):
    customer_id: int
    staff_id: int
    appointment_date: datetime
    service_ids: conlist(int, min_length=1)
    notes: Optional[str] = None
    admin_note: Optional[str] = None
    staff_note: Optional[str] = None
    customer_note: Optional[str] = None

class AppointmentUpdate(BaseModel):
    customer_id: Optional[int] = None
    staff_id: Optional[int] = None
    appointment_date: Optional[datetime] = None
    service_ids: Optional[conlist(int, min_length=1)] = None
    notes: Optional[str] = None
    status: Optional[Literal['pending', 'scheduled', 'completed', 'cancelled', 'rejected', 'no_show']] = None
    admin_note: Optional[str] = None
    staff_note: Optional[str] = None
    customer_note: Optional[str] = None

class AppointmentStatusUpdate(BaseModel):
    status: Literal['pending', 'scheduled', 'completed', 'cancelled', 'rejected', 'no_show']

# Appointment Service Nested (for appointment list with services)
# AppointmentResponse'dan önce tanımlanmalı (forward reference için)
class AppointmentServiceNestedResponse(BaseResponseModel):
    service_id: int
    name: str
    duration_minutes: int
    price: Decimal  # appointment_services.price
    created_at: datetime

class AppointmentResponse(BaseResponseModel):
    id: int
    business_id: int
    customer_id: int
    staff_id: int
    appointment_date: datetime
    status: Literal['pending', 'scheduled', 'completed', 'cancelled', 'rejected', 'no_show']
    notes: Optional[str]
    admin_note: Optional[str] = None
    staff_note: Optional[str] = None
    customer_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    customer_full_name: Optional[str] = None
    staff_full_name: Optional[str] = None
    services: Optional[List[AppointmentServiceNestedResponse]] = None
    transaction: Optional[dict] = None  # Transaction details if available

# Appointment Service (for nested responses)
class AppointmentServiceResponse(BaseResponseModel):
    id: int
    appointment_id: int
    service_id: int
    price: Decimal
    created_at: datetime

# Transaction
class TransactionCreate(BaseModel):
    appointment_id: Optional[int] = None
    customer_id: int
    amount: Decimal
    payment_method: Literal['cash', 'card', 'online']
    status: Literal['pending', 'completed', 'refunded'] = 'pending'
    idempotency_key: Optional[str] = None

class TransactionUpdate(BaseModel):
    payment_method: Optional[Literal['cash', 'card', 'online']] = None
    status: Optional[Literal['pending', 'completed', 'refunded']] = None

# Booking Links
class BookingLinkCreate(BaseModel):
    name: str
    description: Optional[str] = None
    service_ids: Optional[List[int]] = None
    staff_ids: Optional[List[int]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_uses: Optional[int] = None
    is_active: bool = True

class BookingLinkUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    service_ids: Optional[List[int]] = None
    staff_ids: Optional[List[int]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_uses: Optional[int] = None
    is_active: Optional[bool] = None

class BookingLinkResponse(BaseResponseModel):
    id: int
    business_id: int
    token: str
    name: str
    description: Optional[str]
    service_ids: Optional[List[int]]
    staff_ids: Optional[List[int]]
    start_date: Optional[str]
    end_date: Optional[str]
    max_uses: Optional[int]
    current_uses: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

# Public Booking
class PublicBookingCreate(BaseModel):
    customer_name: str
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    service_ids: List[int]
    staff_id: int
    appointment_date: str  # ISO format datetime string
    notes: Optional[str] = None

class TransactionResponse(BaseResponseModel):
    id: int
    business_id: int
    appointment_id: Optional[int]
    customer_id: int
    amount: Decimal
    payment_method: Literal['cash', 'card', 'online']
    status: Literal['pending', 'completed', 'refunded']
    transaction_date: datetime
    created_at: datetime

# Business Settings
class BusinessSettingsUpdate(BaseModel):
    slot_length_minutes: Optional[int] = None
    buffer_time_minutes: Optional[int] = None
    cancellation_hours: Optional[int] = None
    working_hours_start: Optional[time] = None
    working_hours_end: Optional[time] = None
    timezone: Optional[str] = None

class BusinessSettingsResponse(BaseResponseModel):
    id: int
    business_id: int
    slot_length_minutes: int
    buffer_time_minutes: int
    cancellation_hours: int
    working_hours_start: time
    working_hours_end: time
    timezone: str
    created_at: datetime
    updated_at: datetime

# Reports
class TopSellingServiceResponse(BaseResponseModel):
    """Top selling service report response model"""
    id: int
    name: str
    booking_count: int  # Number of completed appointments (distinct appointment_id)
    total_revenue: Decimal  # Total revenue from completed appointments (string in JSON)

# Available Slots
class AvailableSlotsResponse(BaseResponseModel):
    """Available appointment slots response model"""
    available_slots: List[str]  # List of ISO format datetime strings
    timezone: str  # Timezone string (e.g., "UTC", "Europe/Istanbul")
    slot_duration_minutes: int  # Duration of each slot in minutes

# Customer History
class CustomerHistoryAppointmentResponse(BaseResponseModel):
    """Appointment in customer history"""
    id: int
    business_id: int
    customer_id: int
    staff_id: int
    appointment_date: datetime
    status: Literal['pending', 'scheduled', 'completed', 'cancelled', 'rejected', 'no_show']
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    services: List[AppointmentServiceNestedResponse]  # Nested services

class CustomerHistoryResponse(BaseResponseModel):
    """Customer history response model"""
    customer: CustomerResponse
    total_spent: Decimal  # Total spending from completed transactions
    last_appointment: Optional[CustomerHistoryAppointmentResponse]  # Most recent appointment
    appointments: List[CustomerHistoryAppointmentResponse]  # All appointments
