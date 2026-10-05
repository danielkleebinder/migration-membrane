# Setup nftables for routing pakets on a kernel level directly from the sensor over sat2 to sat1.
# This is a configuration based on nftables (nft) for sat2.

# Allow IP forwarding on a linux kernel level
sudo sysctl -w net.ipv4.ip_forward=1

# Create a dedicated NAT table
sudo nft add table ip nat

# 3. Create base chains for rewriting the source and destination address
sudo nft 'add chain ip nat prerouting { type nat hook prerouting priority dstnat; }'
sudo nft 'add chain ip nat postrouting { type nat hook postrouting priority srcnat; }'

# 4. Destination NAT (DNAT): Reroute requests on port 8080 to sat1 (192.168.10.11)
sudo nft add rule ip nat prerouting tcp dport 8080 counter dnat to 192.168.10.11:8080

# 5. Source NAT (MASQUERADE): Route answers from sat1 back to the sensor
sudo nft add rule ip nat postrouting ip daddr 192.168.10.11 tcp dport 8080 masquerade
