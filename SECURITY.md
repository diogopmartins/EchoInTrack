# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| v10     | :white_check_mark: |
| < v10   | :x:                |

## Security Best Practices

### Environment Variables

**Always set these environment variables in production:**

1. **SECRET_KEY**: A strong, random secret key (minimum 24 characters)
   - Generate with: `python -c "import secrets; print(secrets.token_hex(24))"`
   - Never commit this to version control

2. **ADMIN_PASSWORD**: Strong password for the default admin user
   - Use a complex password with mixed case, numbers, and symbols
   - Change immediately after first login

3. **FLASK_DEBUG**: Always set to `False` in production
   - Debug mode exposes sensitive information and should never be used in production

### Configuration Files

- Never commit `config.json` with sensitive data
- Use `config.json.example` as a template
- Review all configuration values before deployment

### Database Security

- Database files (`.db`, `.sqlite`, `.sqlite3`) are excluded from version control
- Keep database backups secure
- Regularly backup your database
- Use proper file permissions on database files

### Authentication

- Change default admin password immediately after first deployment
- Use strong passwords for all user accounts
- Consider implementing password complexity requirements
- Regularly review user accounts

### Reporting a Vulnerability

If you discover a security vulnerability, please report it privately by opening an issue with the "security" label. Do not disclose publicly until it has been addressed.

## Security Checklist for Deployment

- [ ] Set `SECRET_KEY` environment variable
- [ ] Set `ADMIN_PASSWORD` environment variable
- [ ] Set `FLASK_DEBUG=False`
- [ ] Review and customize `config.json`
- [ ] Change default admin password after first login
- [ ] Ensure database files are not publicly accessible
- [ ] Use HTTPS in production
- [ ] Keep dependencies up to date
- [ ] Regularly review access logs
- [ ] Implement proper firewall rules

