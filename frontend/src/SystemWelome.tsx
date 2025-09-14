
import React, { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";


function SystemWelcome({ space }: { space: string }) {
    return (
      <div>
        <div className="font-medium">Welcome! 👋</div>
        <div className="text-neutral-300 mt-1">
          We’ll focus on <span className="text-neutral-100 font-semibold">{space}</span>. Ask anything to kick off
          research.
        </div>
        <ul className="list-disc pl-5 text-neutral-400 mt-2">
          <li>“Audit current land use and amenity gaps around {space}.”</li>
          <li>“Compare: grocery hub vs. green corridor vs. mixed-use for {space}.”</li>
          <li>“What metrics measure happiness/time saved/economic uplift here?”</li>
        </ul>
      </div>
    );
  }

export default SystemWelcome;


