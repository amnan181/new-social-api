from graphene import (
    Date,
    Mutation as ObjectMutation,
    Boolean,
    String,
    ObjectType,
    List as GList,
    Field
)
from graphql.execution import ResolveInfo
from starlette.background import BackgroundTasks
import typing
from .utils import (
    validate_password,
    OTHER, MALE, FEMALE,
    send_signup_activation_code,
    USE_EMAIL,
    USE_PHONE_NUMBER,
    insert_new_user,
    send_reset_code
)
from validate_email import validate_email
from sqlalchemy.engine.result import ResultProxy
from sqlalchemy import select, or_
from .security import check_password, encrypt_password
import jwt
from datetime import timedelta, datetime, date
from social_api import config
import logging
from phonenumbers import parse, is_valid_number
from phonenumbers.phonenumber import PhoneNumber
from collections import defaultdict
from social_api.db.common import fetch_one_record_filter_by_one_field, fetch_one_record_with_query
from .model import UserTable


class SignupError(ObjectType):
    email_or_phone = GList(String, required=False)
    password = GList(String, required=False)
    username = GList(String, required=False)
    date_of_birth = GList(String, required=False)
    general = GList(String, required=False)


class Signup(ObjectMutation):
    ok = Boolean(required=True)
    errors = Field(SignupError, required=False)

    class Arguments:
        gender = String(required=True)
        email_or_phone = String(required=True)
        username = String(required=True)
        date_of_birth = Date(required=True)
        password1 = String(required=True)
        password2 = String(required=True)

    async def mutate(self, info: ResolveInfo, **kwargs):
        ok: bool = False
        errors: defaultdict = defaultdict(list)

        # decide the user is using email or phone number:
        emailOrPhone: typing.Union[str, None] = None
        encryptedPassword: typing.Union[str, None] = None

        username: str = kwargs.get('username', '').strip()
        gender: str = kwargs.get('gender', '').strip().lower()
        email_or_phone: str = kwargs.get('email_or_phone', '').strip()
        date_of_birth: typing.Union[
            datetime, None] = kwargs.get('date_of_birth', None)
        password1: str = kwargs.get('password1', '').strip()
        password2: str = kwargs.get('password2', '').strip()

        if all([bool(value) for value in (username, email_or_phone, date_of_birth, password1, password2)]):
            # check email valid:
            if validate_email(email=email_or_phone):
                # => user is using email for registration
                emailOrPhone = USE_EMAIL
            else:
                try:
                    # phone number needs to be in format of: country code + phone number
                    # e.g: phone numbers for viet nam: +8456986768
                    phoneNumber: PhoneNumber = parse(number=email_or_phone)
                except Exception as e:
                    errors['email_or_phone'].append(
                        f"{email_or_phone!r} is not a valid phone number or email address.")
                else:
                    if is_valid_number(phoneNumber):
                        emailOrPhone = USE_PHONE_NUMBER

            if emailOrPhone in [USE_EMAIL, USE_PHONE_NUMBER]:
                query: typing.Any = select([UserTable]).where(
                    or_(
                        UserTable.c.email == email_or_phone,
                        UserTable.c.phone_number == email_or_phone
                    )
                )
                # fetch user
                existingUserWithEmailOrPhone: typing.Union[typing.Mapping, None] = await fetch_one_record_with_query(
                    query=query
                )

                # the user with email || phone number does exist
                if not existingUserWithEmailOrPhone is None:
                    errors['email_or_phone'].append(f"Email {email_or_phone!r} is already taken."
                                                    if emailOrPhone == USE_EMAIL else f"Phone number {email_or_phone!r} is already taken.")
                # now we must check 'username'
                existingUserWithUsername: typing.Union[typing.Mapping, None] = await fetch_one_record_filter_by_one_field(
                    table=UserTable, filterField='username', filterValue=username
                )
                if not existingUserWithUsername is None:
                    # user with this 'username' is already exist.
                    errors['username'].append(
                        f"Username {username!r} is already taken.")
            else:
                errors['email_or_phone'].append(
                    'Please enter a valid email or phone number.')

            # check passwords match:
            if password1 != password2:
                errors['password'].append('Passwords do not match.')
            else:
                passwordValidationErrors: typing.List[str] = validate_password(
                    password=password1)
                if not len(passwordValidationErrors):
                    # now we encrypt password to make it to be impossible to decode
                    encryptedPassword = encrypt_password(
                        password=password1)
                else:
                    errors['password'].extend(passwordValidationErrors)

            # check gender:
            if not gender in [MALE, FEMALE, OTHER]:
                gender = OTHER

            # check date_of_birth is instance of datetime or not:
            if not isinstance(date_of_birth, date):
                errors['date_of_birth'].append(
                    'Please enter correct date of birth.')
        else:
            errors['general'].append(
                'Please enter all the required fields correctly.')

        if not len(errors):
            # ordereddict can also be measured
            ok = True
            newUserData: typing.Mapping[str, typing.Any] = {
                'date_of_birth': date_of_birth,
                'username': username,
                'hashed_password': encryptedPassword,
                'gender': gender,
                'active': False
            }
            # set email or phone_number
            newUserData['email' if emailOrPhone ==
                        USE_EMAIL else 'phone_number'] = email_or_phone

        if ok:
            background: BackgroundTasks = info.context['background']
            background.add_task(send_signup_activation_code,
                                emailOrPhone, email_or_phone)

            # add user into table
            background.add_task(insert_new_user, newUserData)

        return Signup(
            ok=ok,
            errors=dict(errors)
        )


class Signin(ObjectMutation):
    ok = Boolean(required=True)
    errors = GList(String, required=False)
    token = String(
        required=False
    )

    class Arguments:
        email = String(required=True)
        password = String(required=True)

    async def mutate(self, info: ResolveInfo, **kwargs):
        ok: bool = False
        errors: typing.List[typing.Union[None, str]] = []
        token: str = ''

        email: str = kwargs.get('email', '').strip()
        password: str = kwargs.get('password', '').strip()

        if bool(email and password):
            # check user with this email does exist or not:
            userWithEmail: typing.Union[None, ResultProxy] = await fetch_one_record_filter_by_one_field(
                table=UserTable, filterField='email', filterValue=email
            )
            if userWithEmail is None:
                errors.append(
                    f'We found no account with email {email!r} registered.')
            else:
                # check password if user exist:
                dbPassword: str = userWithEmail['hashed_password']
                if check_password(password, dbPassword):
                    # this user does exist:
                    # then create token:
                    try:
                        token = jwt.encode(
                            payload={
                                'username': userWithEmail['username'],
                                'id': userWithEmail['id'],
                                'expire': (datetime.utcnow() + timedelta(minutes=10)).timestamp()
                            },
                            key=config.get(
                                'SECRET',
                                cast=str,
                                default='@JHSD*(U$JRNDUU#$NKEFE*R()#%NJHFSR*_(#IOFDKEFJ)(#%*$()))'
                            ),
                            algorithm='HS256'
                        ).decode('utf-8')
                    except jwt.PyJWTError as e:
                        logging.error(f'Error encoding token: {e}.')
                    else:
                        # everything was successful
                        ok = True
                else:
                    errors.append('Your password is incorrect.')
        else:
            if not bool(email):
                errors.append('Please enter your email address.')
            if not bool(password):
                errors.append('Please enter your password.')

        return Signin(
            ok=ok,
            errors=errors,
            token=token
        )


class ResetPassword(ObjectMutation):
    ok = Boolean(required=True)
    errors = GList(String, required=True)

    class Arguments:
        email_or_phone_number = String(required=True)

    async def mutate(self, info: ResolveInfo, **kwargs):
        ok: bool = False
        errors: typing.List[str] = []
        # indicate user use email or phone number to reset password.
        useEmailOrPhoneNumber: str = ''

        email_or_phone_number: str = kwargs.get(
            'email_or_phone_number', '').strip()

        if not bool(email_or_phone_number):
            errors.append('Please enter your email.')
        else:
            if not isinstance(email_or_phone_number, str):
                errors.append('Please enter a valid email.')
            else:
                # check if value if 'email' or 'phone_number':
                if validate_email(email=email_or_phone_number):
                    useEmailOrPhoneNumber = USE_EMAIL
                else:
                    try:
                        phoneNumber: PhoneNumber = parse(
                            number=email_or_phone_number)
                    except Exception as e:
                        errors.append(
                            f"The input {email_or_phone_number!r} is not valid email or phone number.")
                    else:
                        if is_valid_number(numobj=phoneNumber):
                            useEmailOrPhoneNumber = USE_PHONE_NUMBER
                # check user exist or not:
                # query 1 recors from db:
                queryResult: typing.Union[None, typing.Mapping] = await fetch_one_record_filter_by_one_field(
                    table=UserTable,
                    filterField=(
                        'email' if useEmailOrPhoneNumber is USE_EMAIL else 'phone_number'),
                    filterValue=email_or_phone_number
                )
                if queryResult is None:
                    # does not exist:
                    errors.append(
                        f"We found no account with the {useEmailOrPhoneNumber} {email_or_phone_number!r} registered.")
                else:
                    # the account with this 'email' or 'phone_number' does exist:
                    ok = True

        if ok:
            # create background task for sending reset code
            background: BackgroundTasks = info.context['background']
            background.add_task(
                send_reset_code,
                'email' if useEmailOrPhoneNumber is USE_EMAIL else 'phone_number',
                email_or_phone_number
            )

        return ResetPassword(
            ok=ok,
            errors=errors
        )


class Mutation(ObjectType):
    signin = Signin.Field()
    signup = Signup.Field()
    reset_password = ResetPassword.Field()
