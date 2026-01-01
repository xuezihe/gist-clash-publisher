server {
    listen 80;
    server_name sub.example.com;

    root /var/www/sub;

    location = /<随机路径>/proxies.yaml {
        auth_basic "Subscription";
        auth_basic_user_file /etc/nginx/.htpasswd;

        default_type text/yaml;
        add_header Cache-Control "no-store";
        try_files /<随机路径>/proxies.yaml =404;
    }

    location / {
        return 404;
    }
}
