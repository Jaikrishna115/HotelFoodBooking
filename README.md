# Hotel Food Booking — The Grand Table website

This is a Django website with PostgreSQL storage. Customers order food in a browser, workers handle their own table orders and assigned customer orders, and Billing manages payments and restaurant settings. The website does not need Flutter or Firebase.

**This computer is already configured.** Open http://127.0.0.1:8000/ and use the private `.local/first-login.txt` file for the initial Billing login. You do not need to repeat the one-time setup below. The supplied starter menu and prices can be changed in Billing → Settings → Menu.

Orders are saved on the server. Keep the server and PostgreSQL running while using the website. There is no offline order queue or automatic sending later. This version records **cash received at the restaurant**; it does not charge a card, use a payment gateway or issue an automatic refund.

## Start here on Windows

The project folder on this computer is:

```text
C:\Users\jaikr\Jk_Projects\HotelFoodBooking
```

`Hotelbooking` inside that folder is the existing Python virtual environment. A virtual environment is a project-specific installation of Python packages. You do not have to activate it manually: the scripts use its Python directly.

### 1. Prepare the PostgreSQL database

Open **pgAdmin** and connect to your PostgreSQL server using the database login and password you configured when PostgreSQL was installed. If `hotelfood_db` already exists, use it. Otherwise, right-click **Databases → Create → Database**, enter `hotelfood_db`, select the intended database owner and save. The database login used by the website must be able to create and update tables in this database.

The two kinds of accounts are different:

| Account | Where it is used | What it controls |
| --- | --- | --- |
| PostgreSQL login | pgAdmin and the local `.env` file | Lets Django connect to the database. Customers and workers never use this password. |
| Website account | The website's sign-in page | Identifies a Customer, Worker or Billing person. These accounts are stored in the database after setup. |

There are no default website credentials. Creating the database does not create a website user.

For the installation prepared on this computer, the first Billing account details are in **`.local\first-login.txt`** inside the project folder. Open that private file to sign in, then change the initial password when asked. Do not share or include that file in a source archive. It is not a universal login for other installations.

### 2. Run the one-time setup

Open **PowerShell** or the terminal in your editor. Run each line separately:

```powershell
cd 'C:\Users\jaikr\Jk_Projects\HotelFoodBooking'
.\setup.ps1
```

The script installs the packages in `requirements.txt`, asks for your PostgreSQL connection details when missing, checks the connection, creates the database tables, adds the starter menu and tables, and starts the first Billing-account setup. Password input is hidden while you type; this is normal. Choose your own email and a strong password for the Billing account.

If PowerShell says that script execution is disabled, use this command for this one script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

The setup script connects to `hotelfood_db`; it does not create the PostgreSQL database itself. If it reports a connection error, check the PostgreSQL service, database name and login details, then run it again.

### 3. Start and open the website

```powershell
.\run.ps1
```

Keep this terminal open, then visit **http://127.0.0.1:8000/** in your browser. `127.0.0.1` means this computer. Press **Ctrl+C** in the terminal to stop the development server. Starting it again keeps the saved database records.

The initial preview was started in the background. `run.ps1` detects that server and shows its address. To stop that prepared background server, run `.\stop.ps1`; to start it again in your own terminal, run `.\run.ps1`. The stop helper verifies the saved process identity before stopping it.

The server binds to this computer only. Opening the same address on a phone points to the phone itself; this local setup is not public hosting.

## Sign in and create restaurant users

### First Billing account

`setup.ps1` runs the trusted `bootstrap_billing` command. You can also run that step directly after the database tables exist:

```powershell
.\Hotelbooking\Scripts\python.exe manage.py bootstrap_billing
```

This is a one-time administrative step performed in the project terminal. Public registration always creates a **Customer**. It cannot grant Worker or Billing access. The website does not expose a generic Django admin page.

After signing in with an initial staff password, complete the required **change password** screen before continuing. The new password should belong only to that employee.

### Subsequent workers and Billing users

1. Sign in as Billing and open **Settings → Users**.
2. Add the person's name and email, choose **Worker** or **Billing**, and enter/confirm an initial password.
3. Give the email and initial password privately to that person.
4. They sign in and must choose a new password before using restaurant pages.

This workflow does not automatically email passwords. Never share the PostgreSQL password with employees. Customers can create their own accounts through the public registration page.

## Who can do what

| Role | Allowed work |
| --- | --- |
| Customer | Browse food, place their own order, see their own orders, request a reservation and cancel their own eligible reservation. |
| Worker | Create dine-in orders for active tables. Change the status of table orders they created and customer orders assigned to them. Request a reservation and cancel their own eligible reservation. |
| Billing | See all orders, assign/reassign active customer orders, record cash actually collected, and manage menu, tables, reservations, restaurant details and users in Settings. |

Billing cannot place food orders or change their preparation status. Workers cannot collect cash or use Settings. A worker cannot change another worker's table order. Customer orders start unassigned; Billing must assign a worker before preparation starts. Reassigning a customer order removes the previous worker's access. Completed and cancelled orders cannot be reassigned.

The normal order sequence is **Placed → Accepted → Preparing → Ready → Completed**. The responsible worker advances it one step at a time. Billing records payment before the worker can complete the order. Cancelling a paid order flags a manual refund; the website does not return money itself or erase the payment record.

## Try one complete order

1. Sign in as Customer and place a takeaway or delivery order.
2. Sign out, then sign in as Billing. Find the order in Counter and assign it to a worker.
3. Sign in as that worker and move it through Accepted, Preparing and Ready.
4. Billing receives the cash and confirms collection on the order.
5. The responsible worker marks the paid order Completed.

For a restaurant table, the worker selects a table and creates the order directly. That order stays with its creator and needs no assignment. Use separate browser profiles or a private window to keep two people signed in at once; ordinary tabs share one login session.

Prices and totals are calculated by Django from the database. Editing a browser field cannot set a cheaper total. Saved order lines retain the dish name and price from the order time, so later menu edits do not rewrite earlier bills. Repeating a confirmed cash-collection request does not create a second payment.

If your connection drops after you submit an order, check **Orders** before starting another checkout. The restaurant may have saved the first request even if the browser did not receive the response.

## Your local configuration

`.env` is a text file in the project root. It holds this computer's configuration. `setup.ps1` creates a random Django secret and asks for missing database credentials; `.env.example` shows the names without real secrets.

| Setting | Meaning |
| --- | --- |
| `DJANGO_SECRET_KEY` | A long random secret used by Django. Setup generates it. Keep it private. |
| `DJANGO_DEBUG` | Use `1` for this local development setup. Production hosting needs separate secure configuration. |
| `DJANGO_ALLOWED_HOSTS` | Local defaults are `127.0.0.1,localhost`. |
| `DB_NAME` | `hotelfood_db`. |
| `DB_USER` / `DB_PASSWORD` | Your PostgreSQL login, not a website account. |
| `DB_HOST` / `DB_PORT` | Usually `127.0.0.1` and `5432` when PostgreSQL runs on this computer. |

Do not commit `.env` or copy it into a shared source ZIP. If your database password changes, update `.env` or run `tools\configure_database.py` with the project Python after removing the outdated password value. Never put database secrets in templates or JavaScript.

## Where the code lives

| Path | Purpose |
| --- | --- |
| `manage.py` | Runs Django commands such as migrations, checks and tests. |
| `config/settings.py` | Reads `.env`; configures PostgreSQL, login, templates and security settings. |
| `config/urls.py` | Connects the website's main URL routes. |
| `restaurant/models.py` | Defines users, dishes, tables, orders, payments and reservations. |
| `restaurant/services.py` | Enforces role permissions and business rules before changing database records. |
| `restaurant/forms.py` | Validates information submitted by a person. |
| `restaurant/views.py` / `urls.py` | Handle requests and select the next page or action. |
| `restaurant/middleware.py` | Requires employees to change an initial password. |
| `restaurant/migrations/` | Versioned instructions for creating/updating database tables. |
| `templates/` / `static/` | HTML pages, CSS, JavaScript and visual assets. |
| `restaurant/tests/` | Automated permission, ordering and payment checks. |
| `tools/`, `setup.ps1`, `run.ps1` | Local configuration and startup helpers. |
| `Hotelbooking/` | Python environment and installed packages; do not edit application code here. |

For a text or visual change, start with templates or CSS. For a rule such as “who may collect cash,” start with the service and its tests. Changes to model fields usually need a migration; do not delete existing migration files or edit production database tables by hand.

## Checks and tests

Check normal configuration and database connectivity:

```powershell
.\Hotelbooking\Scripts\python.exe tools\check_database.py
.\Hotelbooking\Scripts\python.exe manage.py check
```

Run isolated automated tests without using your restaurant database:

```powershell
.\Hotelbooking\Scripts\python.exe manage.py test restaurant.tests --settings=config.test_settings
```

`config.test_settings` uses an in-memory SQLite database only for tests. The website's normal settings always use PostgreSQL. SQLite tests do not establish that PostgreSQL row locking or concurrent requests work correctly; two PostgreSQL-specific regression tests are skipped in that mode.

With your working `.env` database connection, run the real PostgreSQL suite:

```powershell
.\Hotelbooking\Scripts\python.exe manage.py test restaurant.tests --settings=config.postgres_test_settings
```

This configuration creates a new random `hotelfood_qa_...` **schema** inside the connected database. A schema is a separate namespace for tables. Test connections use only that schema and cannot fall back to the application's `public` tables. The runner migrates the test schema, runs the tests and drops only the schema it created. Your login needs permission to create a schema; it does not need permission to create another database. These tests include simultaneous cash-collection requests and order updates with optional table/worker links.

The tests cover permissions and business behaviour. They do not create real accounts on an external service, send real payment transactions or establish production hosting readiness.

## Common first-run problems

| Message or symptom | Next step |
| --- | --- |
| Cannot connect to PostgreSQL | Start the PostgreSQL service, confirm `hotelfood_db` exists, and verify `.env` host, port and login. |
| Password authentication failed | Use the PostgreSQL login password in `.env`; a website password will not work. |
| Missing table or “relation does not exist” | Run `manage.py migrate` with the project Python. |
| “Set DJANGO_SECRET_KEY” | Run setup; make sure `.env` is in the same folder as `manage.py`. |
| Sign-in keeps showing Change password | Finish the initial-password change before opening other pages. |
| Worker cannot see a customer order | Ask Billing to assign it to that worker. |
| Worker cannot complete an order | It must be Ready and Billing must have recorded payment. |
| Terminal says the address/port is in use | Another server may already be running. Use its browser page or stop that server with Ctrl+C. |

`runserver` is a local development server. Public hosting additionally needs a production web server, HTTPS, appropriate domain settings, private database access, backups and a reviewed deployment configuration.
