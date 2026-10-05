sudo ip addr add 192.168.10.100/24 dev enx803f5dfb206d
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -o wlp194s0 -j MASQUERADE
sudo iptables -A FORWARD -i enx803f5dfb206d -o wlp194s0 -j ACCEPT
sudo iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
