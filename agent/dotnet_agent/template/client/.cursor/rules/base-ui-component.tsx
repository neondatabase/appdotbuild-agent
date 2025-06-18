import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { useState } from 'react';
import type { Entity } from '../../../server/src/schema';

interface BaseUIComponentProps {
  title?: string;
  entities?: Entity[];
  isLoading?: boolean;
  onAction?: (action: string, data: any) => void;
}

export default function BaseUIComponent({
  title = 'UI Components Demo',
  entities = [],
  isLoading = false,
  onAction
}: BaseUIComponentProps) {
  const [selectedTab, setSelectedTab] = useState('overview');
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [progress, setProgress] = useState(33);
  const [filters, setFilters] = useState({
    status: 'all',
    includeInactive: false,
    sortBy: 'name'
  });

  const handleAction = (action: string, data?: any) => {
    onAction?.(action, data);
  };

  return (
    <div className="container mx-auto p-6 space-y-8">
      {/* Header Section */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
          <p className="text-muted-foreground">
            Comprehensive UI component examples with Radix UI and Tailwind CSS
          </p>
        </div>
        
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => handleAction('refresh')}>
            Refresh
          </Button>
          <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
            <DialogTrigger asChild>
              <Button>Open Dialog</Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[425px]">
              <DialogHeader>
                <DialogTitle>Example Dialog</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-4">
                <div className="space-y-2">
                  <Label htmlFor="dialog-input">Dialog Input</Label>
                  <Input id="dialog-input" placeholder="Enter some text..." />
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button onClick={() => setIsDialogOpen(false)}>
                    Save
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Alert Examples */}
      <div className="space-y-4">
        <Alert>
          <AlertDescription>
            This is an informational alert with default styling.
          </AlertDescription>
        </Alert>
        
        <Alert variant="destructive">
          <AlertDescription>
            This is an error alert. Use for critical information.
          </AlertDescription>
        </Alert>
      </div>

      {/* Tabs Layout */}
      <Tabs value={selectedTab} onValueChange={setSelectedTab} className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="data">Data</TabsTrigger>
          <TabsTrigger value="forms">Forms</TabsTrigger>
          <TabsTrigger value="status">Status</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          {/* Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  Total Entities
                  <Badge variant="secondary">{entities.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {entities.length.toLocaleString()}
                </div>
                <p className="text-xs text-muted-foreground">
                  {entities.length > 0 ? '+20.1% from last month' : 'No data available'}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Progress Example</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span>Completion</span>
                    <span>{progress}%</span>
                  </div>
                  <Progress value={progress} className="w-full" />
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => setProgress(Math.max(0, progress - 10))}>
                    -10%
                  </Button>
                  <Button size="sm" onClick={() => setProgress(Math.min(100, progress + 10))}>
                    +10%
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button className="w-full" onClick={() => handleAction('create')}>
                  Create New Item
                </Button>
                <Button variant="outline" className="w-full" onClick={() => handleAction('export')}>
                  Export Data
                </Button>
                <Button variant="secondary" className="w-full" onClick={() => handleAction('settings')}>
                  Settings
                </Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="data" className="space-y-6">
          {/* Data Display with Loading States */}
          <Card>
            <CardHeader>
              <CardTitle>Entities List</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-4">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="flex items-center space-x-4">
                      <Skeleton className="h-12 w-12 rounded-full" />
                      <div className="space-y-2 flex-1">
                        <Skeleton className="h-4 w-[250px]" />
                        <Skeleton className="h-4 w-[200px]" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : entities.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-muted-foreground">No entities found.</p>
                  <Button className="mt-4" onClick={() => handleAction('create')}>
                    Create First Entity
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  {entities.slice(0, 5).map((entity: Entity) => (
                    <div key={entity.id} className="flex items-center justify-between p-4 border rounded-lg hover:bg-muted/50 transition-colors">
                      <div className="space-y-1">
                        <h4 className="font-medium">{entity.name}</h4>
                        {entity.description && (
                          <p className="text-sm text-muted-foreground">{entity.description}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">${entity.value.toFixed(2)}</Badge>
                        <Badge variant="secondary">{entity.quantity}</Badge>
                      </div>
                    </div>
                  ))}
                  
                  {entities.length > 5 && (
                    <div className="text-center pt-4">
                      <Button variant="outline" onClick={() => handleAction('viewAll')}>
                        View All {entities.length} Entities
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="forms" className="space-y-6">
          {/* Form Components Examples */}
          <Card>
            <CardHeader>
              <CardTitle>Form Controls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Text Inputs */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="text-input">Text Input</Label>
                  <Input id="text-input" placeholder="Enter text..." />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="number-input">Number Input</Label>
                  <Input id="number-input" type="number" placeholder="0" />
                </div>
              </div>

              <Separator />

              {/* Select and Options */}
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>Select Dropdown</Label>
                  <Select value={filters.status} onValueChange={(value) => setFilters(prev => ({ ...prev, status: value }))}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select status" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Items</SelectItem>
                      <SelectItem value="active">Active Only</SelectItem>
                      <SelectItem value="inactive">Inactive Only</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox 
                    id="include-inactive"
                    checked={filters.includeInactive}
                    onCheckedChange={(checked) => setFilters(prev => ({ ...prev, includeInactive: !!checked }))}
                  />
                  <Label htmlFor="include-inactive">Include inactive items</Label>
                </div>

                <div className="flex items-center justify-between">
                  <Label htmlFor="notifications">Enable notifications</Label>
                  <Switch id="notifications" />
                </div>
              </div>

              <Separator />

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-2">
                <Button>Primary Action</Button>
                <Button variant="secondary">Secondary</Button>
                <Button variant="outline">Outline</Button>
                <Button variant="ghost">Ghost</Button>
                <Button variant="destructive">Destructive</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="status" className="space-y-6">
          {/* Status and State Examples */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Status Badges</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge>Default</Badge>
                  <Badge variant="secondary">Secondary</Badge>
                  <Badge variant="outline">Outline</Badge>
                  <Badge variant="destructive">Destructive</Badge>
                </div>
                
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Active</span>
                    <Badge className="bg-green-100 text-green-800 hover:bg-green-100">
                      Online
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Pending</span>
                    <Badge className="bg-yellow-100 text-yellow-800 hover:bg-yellow-100">
                      Processing
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Error</span>
                    <Badge className="bg-red-100 text-red-800 hover:bg-red-100">
                      Failed
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Loading States</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-4 w-3/5" />
                </div>
                
                <Separator />
                
                <div className="space-y-2">
                  <Button disabled className="w-full">
                    Loading...
                  </Button>
                  <Button variant="outline" disabled className="w-full">
                    Processing...
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      {/* Footer */}
      <div className="text-center text-sm text-muted-foreground pt-8 border-t">
        <p>Built with Radix UI and Tailwind CSS</p>
      </div>
    </div>
  );
}